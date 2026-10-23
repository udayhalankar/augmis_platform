"""No-Docker regression for new bundled React assets checks in C1-D2."""
from io import BytesIO
from email.message import Message
from unittest.mock import patch
import pytest

from services.api.app.services.c1d2_disposable_qualification import (
    _FrontendAssetParser, _verify_frontend_assets, QualificationFailure,
)

class FakeResponse:
    status = 200
    def __init__(self, payload, mime):
        self.file = BytesIO(payload)
        self.headers = Message()
        self.headers['Content-Type'] = mime
    def read(self, n=-1): return self.file.read(n)
    def __enter__(self): return self
    def __exit__(self, *args): return None

HTML = b'<html><head><link rel="stylesheet" href="./assets/index-DJCFvwYI.css"></head><body><script type="module" src="/assets/index-NEBTOIf9.js"></script></body></html>'

def test_parser_finds_relative_vite_assets_only():
    p = _FrontendAssetParser()
    p.feed(HTML.decode() + '<script src="https://evil.example/assets/x.js"></script>')
    assert p.assets == [('/assets/index-DJCFvwYI.css', 'css'), ('/assets/index-NEBTOIf9.js','js')]

def test_real_asset_mime_checked():
    calls = []
    def fetch(req, timeout):
        calls.append(req.full_url)
        if req.full_url.endswith('.css'): return FakeResponse(b'body{}','text/css')
        if req.full_url.endswith('.js'): return FakeResponse(b'console.log(1)','application/javascript')
        return FakeResponse(HTML,'text/html; charset=utf-8')
    with patch('services.api.app.services.c1d2_disposable_qualification.urlopen', side_effect=fetch):
        _verify_frontend_assets('http://127.0.0.1:65531')
    assert len(calls)==3

def test_404_text_plain_fails_closed():
    def fetch(req, timeout):
        if req.full_url.endswith('.js'): return FakeResponse(b'Not found','text/plain')
        if req.full_url.endswith('.css'): return FakeResponse(b'body{}','text/css')
        return FakeResponse(HTML,'text/html')
    with patch('services.api.app.services.c1d2_disposable_qualification.urlopen', side_effect=fetch):
        with pytest.raises(QualificationFailure, match='C1D2_FRONTEND_ASSET_SMOKE_FAILED'):
            _verify_frontend_assets('http://127.0.0.1:65531')

def test_backend_only_no_compiled_assets_does_not_fail():
    with patch('services.api.app.services.c1d2_disposable_qualification.urlopen', return_value=FakeResponse(b'{}','application/json')):
        _verify_frontend_assets('http://127.0.0.1:65531')
