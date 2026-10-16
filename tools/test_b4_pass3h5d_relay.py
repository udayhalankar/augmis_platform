"""Pass3H-5D dev companion relay HTTP allowlist and header discipline."""
import threading
import socket
from urllib.parse import urlsplit
from http.server import ThreadingHTTPServer

import pytest
from tools.b4_dashboard_dev_ingress_relay import server

UPSTREAM='augmis-synthetic-dashboard-1234'

@pytest.fixture
def relay_server(monkeypatch):
    outgoing=[]
    class FakeReply:
        status=200
        def read(self,maxbytes):return b'{"status":"ok"}'
        def getheader(self,name,default=None):return 'application/json'
    class FakeConn:
        def __init__(self,host,port,timeout):
            assert (host,port)==(UPSTREAM,8080)
        def request(self,method,path,headers):outgoing.append((method,path,dict(headers)))
        def getresponse(self):return FakeReply()
        def close(self):pass
    monkeypatch.setattr(server.http.client,'HTTPConnection',FakeConn)
    httpd=ThreadingHTTPServer(('127.0.0.1',0),server.create_handler(UPSTREAM))
    thread=threading.Thread(target=httpd.serve_forever,daemon=True)
    thread.start()
    try:yield 'http://127.0.0.1:'+str(httpd.server_address[1]),outgoing
    finally:
        httpd.shutdown();httpd.server_close();thread.join(timeout=3)


def request(base,path,headers=None,method='GET'):
    info=urlsplit(base)
    lines=[f'{method} {path} HTTP/1.1',f'Host: {info.hostname}:{info.port}','Connection: close']
    for k,v in (headers or {}).items(): lines.append(f'{k}: {v}')
    raw=('\r\n'.join(lines)+'\r\n\r\n').encode('ascii')
    with socket.create_connection((info.hostname, info.port),timeout=3) as client:
        client.settimeout(3)
        client.sendall(raw)
        pieces=[]
        while True:
            chunk=client.recv(65536)
            if not chunk: break
            pieces.append(chunk)
    message=b''.join(pieces)
    first=message.split(b'\r\n',1)[0]
    return int(first.split()[1]),message.split(b'\r\n\r\n',1)[-1]


def test_approved_dashboard_route_forwards_only_assertion(relay_server):
    url,outgoing=relay_server
    status,_=request(url,'/api/dashboard',{
        'X-Augmis-Runtime-Assertion':'synthetic.jwt.signature',
        'X-Augmis-Tenant-Id':'forged','Authorization':'Bearer nope',
    })
    assert status==200
    assert outgoing==[('GET','/api/dashboard',{
        'Accept-Encoding':'identity','X-Augmis-Runtime-Assertion':'synthetic.jwt.signature'
    })]

@pytest.mark.parametrize('path',['/admin','/api/dashboard?tenantId=2','/robots.txt','/metrics','/docs'])
def test_unlisted_paths_fail_closed(relay_server,path):
    url,calls=relay_server
    assert request(url,path)[0]==404
    assert calls==[]

@pytest.mark.parametrize('path',['/','/app.js','/app.css','/healthz','/api/dashboard'])
def test_dashboard_ui_and_api_are_allowlisted(relay_server,path):
    url,calls=relay_server
    assert request(url,path)[0]==200
    assert calls[-1][1]==path

@pytest.mark.parametrize('method',['POST','PUT','PATCH','DELETE','HEAD','OPTIONS'])
def test_write_methods_rejected(relay_server,method):
    url,calls=relay_server
    assert request(url,'/api/dashboard',method=method)[0]==405
    assert calls==[]

@pytest.mark.parametrize('bad',['evil.internal','localhost','127.0.0.1','augmis-','augmis-dashboard/../../'])
def test_relay_does_not_allow_arbitrary_upstream(bad):
    with pytest.raises(ValueError):server.validate_target(bad)
