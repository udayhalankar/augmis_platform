"""Development-only restricted relay; NEVER has credentials or private keys.

The application itself verifies signed, body-bound and instance-bound tokens.
"""
import http.client
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

TARGET_RE = re.compile(r'augmis-[a-z0-9][a-z0-9-]{0,160}\Z')
ITEM = re.compile(r'/api/records/[0-9a-f-]{36}\Z')
MAX_REQ = 1_048_576
MAX_RES = 4_194_304


# AUGMIS_C1D3_ASSET_ALLOWLIST_V1
# Only immutable frontend build assets (not arbitrary paths or API endpoints).
_ASSET_PATH = re.compile(
    r'/assets/[A-Za-z0-9][A-Za-z0-9_-]{0,127}\.(?:js|css|svg|png|jpe?g|webp|woff2?)\Z'
)


def _asset_allowed(method, path):
    return method == 'GET' and _ASSET_PATH.fullmatch(path) is not None


def allowed(method, path):
    if _asset_allowed(method, path):
        return True
    return ((method == 'GET' and (path in {'/', '/health', '/api/records', '/api/summary'} or ITEM.fullmatch(path)))
            or (method == 'POST' and path == '/api/records')
            or (method in {'PUT', 'DELETE'} and ITEM.fullmatch(path)))


def _declared_allowed(method, path, contracts, health):
    if _asset_allowed(method, path):
        return True
    if method == 'GET' and path in {'/', health}:
        return True
    if '%' in path or '?' in path or '#' in path or '\\' in path or '..' in path or '//' in path:
        return False
    for item in contracts:
        template = item['path']
        pattern = '^'+re.escape(template).replace(re.escape('{id:uuid}'),
            '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')+'$'
        if method in item['methods'] and re.fullmatch(pattern,path):
            return True
    return False


def _relay_contract():
    raw=os.environ.get('AUGMIS_RELAY_ROUTE_CONTRACT','')
    if not raw:return None
    # Fail closed for invalid manifests; the relay is not an authorization server.
    parsed=json.loads(raw)
    if not isinstance(parsed,list) or not 1<=len(parsed)<=32:
        raise ValueError('Invalid relay route contract')
    seen=set()
    for item in parsed:
        if not isinstance(item,dict) or set(item)!={'path','methods'}:
            raise ValueError('Invalid relay route entry')
        path=item['path'];methods=item['methods']
        if not isinstance(path,str) or not re.fullmatch(r'/api(?:/[a-z][a-z0-9-]{0,60}|/\{id:uuid\}){1,4}',path):
            raise ValueError('Invalid relay route path')
        if (path in seen or not isinstance(methods,list) or not methods or
            len(set(methods))!=len(methods) or any(method not in {'GET','POST','PUT','PATCH','DELETE'} for method in methods)):
            raise ValueError('Invalid relay route methods')
        seen.add(path)
    return parsed


def create_handler(target):
    if not TARGET_RE.fullmatch(target):
        raise ValueError('Invalid upstream name')
    routes=_relay_contract()
    port_raw=os.environ.get('AUGMIS_RELAY_UPSTREAM_PORT','8080')
    port=int(port_raw)
    health=os.environ.get('AUGMIS_RELAY_HEALTH_PATH','/health')
    if not 1<=port<=65535 or not re.fullmatch(r'/[a-zA-Z0-9/_-]{0,120}',health) or '..' in health:
        raise ValueError('Invalid relay health contract')
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        server_version = 'AugmisCrudDevRelay/0.1'
        def log_message(self, *_): pass
        def reply(self, status, body=b'', content_type='text/plain'):
            self.send_response(status)
            for k,v in {'Content-Type':content_type,'Content-Length':str(len(body)),
                         'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
                         'Connection':'close'}.items(): self.send_header(k,v)
            self.end_headers()
            if body: self.wfile.write(body)
            self.close_connection = True
        def serve(self):
            url = urlsplit(self.path)
            if (url.scheme or url.netloc or url.fragment or len(self.path)>2048 or
                    not (_declared_allowed(self.command,url.path,routes,health) if routes is not None
                         else allowed(self.command,url.path))):
                return self.reply(404,b'Not found')
            if self.headers.get('Transfer-Encoding'):
                return self.reply(400,b'Unsupported encoding')
            sizes = self.headers.get_all('Content-Length', [])
            if len(sizes)>1: return self.reply(400,b'Invalid size')
            try: n=int(sizes[0]) if sizes else 0
            except ValueError: return self.reply(400,b'Invalid size')
            if n<0 or n>MAX_REQ: return self.reply(413,b'Request too large')
            tokens=self.headers.get_all('X-Augmis-Runtime-Assertion', [])
            if len(tokens)>1 or (tokens and (not tokens[0] or len(tokens[0])>8192)):
                return self.reply(400,b'Invalid token')
            if url.path.startswith('/api/') and not tokens:
                return self.reply(401,b'Signed request required')
            body=self.rfile.read(n) if n else b''
            headers={'Accept-Encoding':'identity'}
            if tokens: headers['X-Augmis-Runtime-Assertion']=tokens[0]
            if self.command in {'POST','PUT','PATCH'}:
                if not self.headers.get('Content-Type','').startswith('application/json'):
                    return self.reply(415,b'JSON required')
                headers['Content-Type']='application/json'
            upstream=url.path+('?' + url.query if url.query else '')
            try:
                conn=http.client.HTTPConnection(target,port,timeout=10)
                try:
                    conn.request(self.command,upstream,body=body if body else None,headers=headers)
                    response=conn.getresponse()
                    data=response.read(MAX_RES+1)
                    if len(data)>MAX_RES: return self.reply(502,b'Response too large')
                    content=response.getheader('Content-Type','application/octet-stream')
                    if '\r' in content or '\n' in content:return self.reply(502,b'Invalid response')
                    return self.reply(response.status,data,content)
                finally:conn.close()
            except (OSError,http.client.HTTPException,TimeoutError):
                return self.reply(502,b'Upstream unavailable')
        do_GET=do_POST=do_PUT=do_PATCH=do_DELETE=serve
        def do_HEAD(self): self.reply(405,b'Method not allowed')
        def do_OPTIONS(self): self.reply(405,b'Method not allowed')
    return Handler


if __name__=='__main__':
    ThreadingHTTPServer(('0.0.0.0',18080),create_handler(os.environ.get('AUGMIS_RELAY_UPSTREAM',''))).serve_forever()
