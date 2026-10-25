"""R04 bounded runtime gateway / production auth defenses, no external services."""
from __future__ import annotations
import asyncio
import sys
import types
import pytest
from fastapi import HTTPException, Request
from services.api.app.services.r04_abuse_controls import (
    bounded_gateway_body, bounded_upstream_read, enforce_login_account_rate,
)


def fake_request(chunks: list[bytes], declared: str | None = None):
    headers = []
    if declared is not None:
        headers.append((b"content-length", declared.encode()))
    messages = [dict(type="http.request", body=c, more_body=i < len(chunks) - 1)
                for i, c in enumerate(chunks)]
    if not messages:
        messages = [dict(type="http.request", body=b"", more_body=False)]
    async def receive():
        return messages.pop(0) if messages else dict(type="http.disconnect")
    return Request({"type": "http", "method": "POST", "path": "/api/v1/runtime-gateway/x/api/items",
                    "headers": headers, "query_string": b"", "http_version": "1.1", "scheme": "http"}, receive)


def test_gateway_accepts_bounded_chunked_body():
    assert asyncio.run(bounded_gateway_body(fake_request([b"ab", b"cd"]), 4)) == b"abcd"


def test_gateway_rejects_oversized_chunked_body():
    with pytest.raises(HTTPException) as err:
        asyncio.run(bounded_gateway_body(fake_request([b"ab", b"cde"]), 4))
    assert err.value.status_code == 413


def test_gateway_rejects_declared_large_before_read():
    with pytest.raises(HTTPException) as err:
        asyncio.run(bounded_gateway_body(fake_request([b"a"], "90000"), 4))
    assert err.value.detail == "R04_GATEWAY_REQUEST_TOO_LARGE"


def test_gateway_rejects_invalid_length():
    with pytest.raises(HTTPException) as err:
        asyncio.run(bounded_gateway_body(fake_request([b"a"], "negative"), 4))
    assert err.value.status_code == 400


class Upstream:
    def __init__(self, data, length=None): self.data, self.length = data, length
    def getheader(self, name): return self.length if name == "Content-Length" else None
    def read(self, limit): return self.data[:limit]


def test_upstream_response_bounded():
    assert bounded_upstream_read(Upstream(b"good"), 4) == b"good"
    with pytest.raises(HTTPException) as err:
        bounded_upstream_read(Upstream(b"123456"), 4)
    assert err.value.status_code == 502


def test_upstream_declared_oversize_rejected():
    with pytest.raises(HTTPException) as err:
        bounded_upstream_read(Upstream(b"", "100"), 4)
    assert err.value.detail == "R04_GATEWAY_RESPONSE_TOO_LARGE"


def test_upstream_invalid_content_length_still_bounded():
    with pytest.raises(HTTPException):
        bounded_upstream_read(Upstream(b"123456", "garbage"), 4)


def test_development_account_rate_is_unmodified(monkeypatch):
    monkeypatch.delenv("AUGMIS_ABUSE_REDIS_URL", raising=False)
    enforce_login_account_rate("tester@example.test", environment="development", secret="test-only")


@pytest.fixture
def fake_redis(monkeypatch):
    store = {}
    class Client:
        def eval(self, lua, nk, key, ttl):
            assert "INCR" in lua and "EXPIRE" in lua and key.startswith("augmis:abuse:v1:login:")
            store[key] = store.get(key, 0) + 1
            return store[key]
    class Redis:
        @staticmethod
        def from_url(url, **options):
            assert url.startswith("rediss://") and options["ssl_cert_reqs"] == "required"
            return Client()
    def validate(url):
        if url != "rediss://limiter:pass@redis.internal:6379":
            raise RuntimeError("R03_PRODUCTION_REDIS_TLS_ACL_REQUIRED")
    monkeypatch.setitem(sys.modules, "redis", types.SimpleNamespace(Redis=Redis))
    monkeypatch.setitem(sys.modules, "services.api.app.services.shared_runtime_sessions",
                        types.SimpleNamespace(_production_redis_url=validate))
    monkeypatch.setenv("AUGMIS_ABUSE_REDIS_URL", "rediss://limiter:pass@redis.internal:6379")
    return store


def test_redis_global_rate_window_blocks_after_limit(fake_redis):
    for i in range(20):
        enforce_login_account_rate(" User@Example.test ", environment="production", secret="unit-test-key")
    with pytest.raises(HTTPException) as err:
        enforce_login_account_rate("user@example.test", environment="prod", secret="unit-test-key")
    assert err.value.status_code == 429 and err.value.headers["Retry-After"] == "300"
    assert len(fake_redis) == 1


def test_rate_account_isolation(fake_redis):
    enforce_login_account_rate("user1@example.test", environment="prod", secret="unit-test-key")
    enforce_login_account_rate("user2@example.test", environment="prod", secret="unit-test-key")
    assert len(fake_redis) == 2


def test_rate_missing_secure_store_fails_closed(fake_redis, monkeypatch):
    monkeypatch.delenv("AUGMIS_ABUSE_REDIS_URL")
    with pytest.raises(HTTPException) as err:
        enforce_login_account_rate("u@example.test", environment="production", secret="unit-test-key")
    assert err.value.status_code == 503


def test_rate_connection_failure_fails_closed(fake_redis, monkeypatch):
    mod = sys.modules["redis"]
    monkeypatch.setattr(mod.Redis, "from_url", lambda *a, **kw: (_ for _ in ()).throw(OSError("credential value")))
    with pytest.raises(HTTPException) as err:
        enforce_login_account_rate("u@example.test", environment="production", secret="unit-test-key")
    assert err.value.status_code == 503
    assert "credential" not in err.value.detail
