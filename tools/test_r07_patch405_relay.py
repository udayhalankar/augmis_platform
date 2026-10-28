"""R07 regression: manifest-authorized PATCH forwarding in the development relay.
No Docker/DB/app network connections; HTTP upstream replaced with an in-memory spy.
"""
from __future__ import annotations
import importlib.util
import io
import json
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest


def _relay():
    source = Path(__file__).resolve().parent / "c1b4_crud_dev_ingress_relay" / "server.py"
    spec = importlib.util.spec_from_file_location("r07_patch_relay", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROUTES = [
    {"path": "/api/stock", "methods": ["GET", "POST", "PATCH", "DELETE"]},
    {"path": "/api/stock/receive", "methods": ["POST"]},
]


def _run_request(monkeypatch, *, method="PATCH", path="/api/stock", token="signed-assertion-test",
                 body=b'{"item_name":"R07 edited"}', content_type="application/json", routes=ROUTES):
    relay = _relay()
    monkeypatch.setenv("AUGMIS_RELAY_ROUTE_CONTRACT", json.dumps(routes))
    relayed = []
    class StubResponse:
        status = 200
        def read(self, maximum):
            return b'{"ok":true}'
        def getheader(self, key, default=None):
            return "application/json" if key == "Content-Type" else default
    class StubConnection:
        def __init__(self, host, port, timeout):
            relayed.append(("connection", host, port, timeout))
        def request(self, request_method, target, body=None, headers=None):
            relayed.append(("request", request_method, target, body, dict(headers or {})))
        def getresponse(self):
            return StubResponse()
        def close(self):
            pass
    monkeypatch.setattr(relay.http.client, "HTTPConnection", StubConnection)
    handler_type = relay.create_handler("augmis-r07-upstream")
    # The dispatched method itself must be the forwarder, not an overriding 405 handler.
    if method == "PATCH":
        assert handler_type.do_PATCH is handler_type.serve
    headers = Message()
    headers.add_header("Content-Length", str(len(body)))
    if token is not None:
        headers.add_header("X-Augmis-Runtime-Assertion", token)
    if content_type is not None:
        headers.add_header("Content-Type", content_type)
    calls = []
    handler = object.__new__(handler_type)
    handler.path = path
    handler.command = method
    handler.headers = headers
    handler.rfile = io.BytesIO(body)
    handler.reply = lambda status, reply_body=b'', content_type='text/plain': calls.append((status, reply_body, content_type))
    getattr(handler_type, "do_" + method)(handler)
    return calls, relayed


def test_manifest_authorized_patch_forwards_signed_body_and_json_header(monkeypatch):
    result, relayed = _run_request(monkeypatch, path='/api/stock?source=r07')
    assert result == [(200, b'{"ok":true}', "application/json")]
    assert relayed[0] == ("connection", "augmis-r07-upstream", 8080, 10)
    assert relayed[1] == ("request", "PATCH", "/api/stock?source=r07",
                          b'{"item_name":"R07 edited"}',
                          {"Accept-Encoding":"identity","X-Augmis-Runtime-Assertion":"signed-assertion-test",
                           "Content-Type":"application/json"})


@pytest.mark.parametrize('method,path', [
    ('PATCH','/api/stock/receive'), ('PATCH','/api/admin'),
    ('PATCH','/api/stock/%2e%2e'), ('PATCH','/api/stock/../admin'),
    ('GET','/api/admin'), ('HEAD','/api/stock'), ('OPTIONS','/api/stock'),
])
def test_only_declared_methods_and_paths_reach_upstream(monkeypatch,method,path):
    result, relayed = _run_request(monkeypatch, method=method, path=path)
    assert result[0][0] in (404,405)
    assert not relayed


def test_patch_requires_assertion(monkeypatch):
    result, relayed = _run_request(monkeypatch, token=None)
    assert result[0][0] == 401
    assert relayed == []


@pytest.mark.parametrize('content_type', [None, 'text/plain','application/x-www-form-urlencoded'])
def test_patch_only_forwards_json_payload(monkeypatch, content_type):
    result, relayed = _run_request(monkeypatch, content_type=content_type)
    assert result[0][0] == 415
    assert relayed == []


def test_undeclared_patch_denied_even_with_valid_assertion(monkeypatch):
    result, relayed = _run_request(monkeypatch, routes=[{"path":"/api/stock", "methods":["GET", "POST"]}])
    assert result[0][0] == 404
    assert not relayed


def test_legacy_relay_does_not_start_permitting_patch():
    assert _relay().allowed('PATCH','/api/records') is False
