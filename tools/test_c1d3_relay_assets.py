"""Regression assertions against the EXISTING B4 development relay.
Tests affect no Docker or database records.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'tools/c1b4_crud_dev_ingress_relay/server.py'
spec = importlib.util.spec_from_file_location('augmis_c1d3_existing_dev_relay', MODULE)
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)
CONTRACT = [{'path': '/api/requests', 'methods': ['GET', 'POST', 'PATCH', 'DELETE']}]


def test_vite_js_css_forwarded_under_declared_contract():
    for path in ['/assets/index-B2rZQlk2.js', '/assets/index-DJCFvwYI.css']:
        assert relay._declared_allowed('GET', path, CONTRACT, '/health')
        assert relay.allowed('GET', path)


def test_asset_route_rejects_write_and_traversal():
    for path in ['/assets/../secret.js', '/assets/.env', '/assets/a.js/../b.js',
                 '/assets/a.js%2Fetc', '/assets/x.html', '/assets/x.js.map',
                 '/api/secrets', '/anything.js', '/assets/x.js/']:
        assert not relay._declared_allowed('GET', path, CONTRACT, '/health')
    for method in ['POST', 'PATCH', 'PUT', 'DELETE', 'HEAD']:
        assert not relay._declared_allowed(method, '/assets/index-B2rZQlk2.js', CONTRACT, '/health')


def test_api_gateway_auth_route_contract_unchanged():
    assert relay._declared_allowed('GET', '/', CONTRACT, '/health')
    assert relay._declared_allowed('GET', '/health', CONTRACT, '/health')
    assert relay._declared_allowed('GET', '/api/requests', CONTRACT, '/health')
    assert not relay._declared_allowed('GET', '/api/undeclared', CONTRACT, '/health')
    assert not relay._declared_allowed('POST', '/api/undeclared', CONTRACT, '/health')
    assert not relay._declared_allowed('GET', '/favicon.ico', CONTRACT, '/health')


def test_real_http_relay_forwards_assets_and_keeps_api_unsigned_denial(monkeypatch):
    import json
    import threading
    from http.server import ThreadingHTTPServer
    import http.client

    forwarded = []

    class UpstreamResponse:
        status = 200
        def read(self, limit):
            return b'console.log("ok")'
        def getheader(self, name, default=None):
            return 'application/javascript' if name == 'Content-Type' else default

    class UpstreamConnection:
        def __init__(self, *args, **kwargs):
            pass
        def request(self, method, path, **kwargs):
            forwarded.append((method, path))
        def getresponse(self):
            return UpstreamResponse()
        def close(self):
            pass

    real_connection = http.client.HTTPConnection
    monkeypatch.setenv('AUGMIS_RELAY_ROUTE_CONTRACT', json.dumps(CONTRACT))
    monkeypatch.setattr(relay.http.client, 'HTTPConnection', UpstreamConnection)
    srv = ThreadingHTTPServer(('127.0.0.1', 0), relay.create_handler('augmis-safe-test'))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    def get(path):
        conn = real_connection('127.0.0.1', srv.server_port, timeout=3)
        try:
            conn.request('GET', path)
            response = conn.getresponse()
            return response.status, response.getheader('Content-Type'), response.read()
        finally:
            conn.close()
    try:
        status, content_type, body = get('/assets/index-B2rZQlk2.js')
        assert status == 200
        assert content_type == 'application/javascript'
        assert body == b'console.log("ok")'
        assert forwarded == [('GET', '/assets/index-B2rZQlk2.js')]
        assert get('/api/requests')[0] == 401
        assert get('/assets/../../private.js')[0] == 404
        assert forwarded == [('GET', '/assets/index-B2rZQlk2.js')]
    finally:
        srv.shutdown()
        srv.server_close()
