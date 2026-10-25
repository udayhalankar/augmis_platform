"""R03 fail-closed runtime Redis checks; mocks do not claim live Redis/AWS acceptance.

No network, Docker, databases or Redis server are required. The static ticket
exercise compiles the *actual* route function but limits execution to its ticket
exchange, preventing unrelated application imports and startup side effects.
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.responses import RedirectResponse
from services.api.app.services import shared_runtime_sessions as r03

ROOT = Path(__file__).resolve().parents[1]


class MemoryRedis:
    """Bounded deterministic stand-in for one shared Redis keyspace."""

    def __init__(self):
        self.data = {}
        self.ttls = {}
        self.lock = threading.Lock()
        self.script_calls = 0

    def ping(self):
        return True

    def set(self, key, value, ex=None):
        assert ex is not None and 0 < ex <= 28800
        with self.lock:
            self.data[key] = value
            self.ttls[key] = ex

    def get(self, key):
        with self.lock:
            return self.data.get(key)

    def delete(self, key):
        with self.lock:
            if key not in self.data:
                return 0
            self.data.pop(key)
            self.ttls.pop(key, None)
            return 1

    def scan_iter(self, match, count=100):
        import fnmatch
        with self.lock:
            return iter([k for k in self.data if fnmatch.fnmatch(k, match)])

    def eval(self, script, keys_count, key, expected_hash, now, replacement, purpose):
        assert keys_count == 1
        assert "KEEPTTL" in script
        self.script_calls += 1
        with self.lock:
            raw = self.data.get(key)
            if raw is None:
                return 0
            doc = json.loads(raw)
            field = "ticket_hash" if purpose == "static" else "session_hash"
            if doc.get("ticket_used") or doc.get("ticket_expires_at", 0) <= float(now) or doc.get(field) != expected_hash:
                return 0
            doc["ticket_used"] = True
            if purpose == "static":
                doc["ticket_hash"] = None
                doc["ticket_expires_at"] = 0
                doc["session_hash"] = replacement
            self.data[key] = json.dumps(doc)
            return 1


@pytest.fixture
def fake_settings(monkeypatch):
    cfg = SimpleNamespace(app_env="development")
    monkeypatch.setattr(r03, "settings", cfg)
    return cfg


def fake_redis_client(monkeypatch, client=None):
    client = client or MemoryRedis()
    factory = Mock(return_value=client)
    redis_module = SimpleNamespace(Redis=SimpleNamespace(from_url=factory))
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    return client, factory


@pytest.mark.parametrize("mode", ["memory", "", "MEMORY"])
def test_development_memory_is_unchanged(monkeypatch, fake_settings, mode):
    monkeypatch.setenv("AUGMIS_SESSION_STORE", mode or "memory")
    assert r03.shared_session_map("static") == {}
    assert r03.shared_session_map("container") == {}


def test_redis_store_is_shared_across_workers(monkeypatch, fake_settings):
    client, factory = fake_redis_client(monkeypatch)
    monkeypatch.setenv("AUGMIS_SESSION_STORE", "redis")
    monkeypatch.setenv("AUGMIS_SESSION_REDIS_URL", "redis://localhost:6379/0")
    a = r03.shared_session_map("static")
    b = r03.shared_session_map("static")
    now = time.time()
    a["first"] = {"expires_at": now+90, "ticket_used": False, "ticket_expires_at": now+30, "ticket_hash": "a"*64, "session_hash": None}
    assert b["first"]["ticket_hash"] == "a"*64
    assert b.consume_ticket("first", expected_hash="a"*64, now=now, new_session_hash="b"*64)
    assert not a.consume_ticket("first", expected_hash="a"*64, now=now, new_session_hash="c"*64)
    assert a["first"]["session_hash"] == "b"*64
    assert a["first"]["ticket_used"] is True
    assert factory.call_count == 2


def test_container_ticket_uses_separate_namespace(fake_settings):
    client = MemoryRedis()
    static = r03.RedisSessionMap(client, "static")
    container = r03.RedisSessionMap(client, "container")
    now = time.time()
    value = {"expires_at": now+90, "ticket_used": False, "ticket_expires_at": now+30, "session_hash": "a"*64}
    container["same"] = value
    assert static.get("same") is None
    assert container.consume_ticket("same", expected_hash="a"*64, now=now)
    assert not container.consume_ticket("same", expected_hash="a"*64, now=now)


def test_invalid_key_and_purpose_denied():
    with pytest.raises(ValueError):
        r03.RedisSessionMap(MemoryRedis(), "anything")
    store = r03.RedisSessionMap(MemoryRedis(), "static")
    for key in ("../x", "\x00", "a:b", "a"*161):
        with pytest.raises(ValueError):
            store.get(key)


def test_session_ttl_is_bounded_and_expired_writes_denied():
    client = MemoryRedis()
    store = r03.RedisSessionMap(client, "container")
    now = time.time()
    store["bounded"] = {"expires_at": now+999999}
    assert client.ttls["augmis:runtime:v1:container:bounded"] == 28800
    with pytest.raises(ValueError, match="expired"):
        store["expired"] = {"expires_at": now-3}


@pytest.mark.parametrize("bad", [
    "redis://runtime:password@redis.example:6379/0",
    "rediss://default:password@redis.example:6379/0",
    "rediss://runtime@redis.example:6379/0",
    "rediss://:password@redis.example:6379/0",
    "rediss://runtime:password@redis.example:6379/0?ssl_cert_reqs=none",
    "rediss://runtime:password@redis.example:6379/0#fragment",
    "rediss://runtime:password@redis.example:badport/0",
    "",
])
def test_production_rejects_unsafe_redis_config(monkeypatch, fake_settings, bad):
    fake_settings.app_env = "production"
    monkeypatch.setenv("AUGMIS_SESSION_STORE", "redis")
    monkeypatch.setenv("AUGMIS_SESSION_REDIS_URL", bad)
    with pytest.raises(RuntimeError, match="R03_PRODUCTION_REDIS_TLS_ACL_REQUIRED") as exc:
        r03.shared_session_map("static")
    assert "password" not in str(exc.value)


def test_production_enforces_redis_tls_hostname_and_acl(monkeypatch, fake_settings):
    fake_settings.app_env = "production"
    monkeypatch.setenv("AUGMIS_SESSION_STORE", "redis")
    monkeypatch.setenv("AUGMIS_SESSION_REDIS_URL", "rediss://augmis_runtime:encoded%40secret@private-redis.internal:6379/0")
    client, factory = fake_redis_client(monkeypatch)
    assert isinstance(r03.shared_session_map("container"), r03.RedisSessionMap)
    assert factory.call_args.kwargs["ssl_cert_reqs"] == "required"
    assert factory.call_args.kwargs["ssl_check_hostname"] is True
    assert factory.call_args.kwargs["socket_connect_timeout"] == 3


@pytest.mark.parametrize("env", ["development", "production"])
def test_redis_outage_never_falls_back_or_exposes_secret(monkeypatch, fake_settings, env):
    fake_settings.app_env = env
    monkeypatch.setenv("AUGMIS_SESSION_STORE", "redis")
    url = "rediss://augmis_runtime:HIGHLY_PRIVATE@redis.internal:6379/0"
    monkeypatch.setenv("AUGMIS_SESSION_REDIS_URL", url)
    client, factory = fake_redis_client(monkeypatch)
    client.ping = Mock(side_effect=ConnectionError("HIGHLY_PRIVATE upstream error"))
    with pytest.raises(RuntimeError, match="R03_REDIS_CONNECTION_UNAVAILABLE") as exc:
        r03.shared_session_map("container")
    assert "HIGHLY_PRIVATE" not in str(exc.value)
    assert exc.value.__cause__ is None


def test_production_requires_redis_no_memory(monkeypatch, fake_settings):
    fake_settings.app_env = "prod"
    monkeypatch.setenv("AUGMIS_SESSION_STORE", "memory")
    with pytest.raises(RuntimeError, match="Production runtime requires"):
        r03.shared_session_map("static")


def _load_actual_static_ticket_handler():
    file = ROOT / "services/api/app/routes/subscriptions.py"
    tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "static_runtime")
    fn.decorator_list = []
    fn.args.defaults = [ast.Constant(value=None)]
    scope = {"Request": object, "Session": object, "HTTPException": HTTPException,
             "RedirectResponse": RedirectResponse, "time": time,
             "secrets": __import__("secrets"), "RedisSessionMap": r03.RedisSessionMap,
             "_static_runtime_hash": lambda val: hashlib.sha256(val.encode()).hexdigest(),
             "_static_runtime_cookie_name": lambda runtime_id: "static_"+runtime_id,
             "_STATIC_RUNTIME_SESSION_SECONDS": 28800,
             "_cleanup_static_runtime_sessions": lambda: None,
             "_STATIC_RUNTIME_LOCK": threading.Lock()}
    code = compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(file), "exec")
    exec(code, scope)
    return scope, scope["static_runtime"]


def test_actual_static_gateway_ticket_one_time_exchange_across_workers():
    scope, handler = _load_actual_static_ticket_handler()
    client = MemoryRedis()
    store = r03.RedisSessionMap(client, "static")
    scope["_STATIC_RUNTIME_SESSIONS"] = store
    now = time.time()
    raw_ticket = "opaque-test-ticket"
    digest = hashlib.sha256(raw_ticket.encode()).hexdigest()
    store["abc"] = {"expires_at": now + 90, "ticket_expires_at": now+50,
                    "ticket_hash": digest, "session_hash": None, "ticket_used": False}
    request = SimpleNamespace(query_params={"ticket": raw_ticket}, cookies={}, url=SimpleNamespace(scheme="https"))
    response = handler("abc", request, None)
    assert response.status_code == 303
    assert "secure" in response.headers["set-cookie"].lower()
    assert "httponly" in response.headers["set-cookie"].lower()
    state = r03.RedisSessionMap(client, "static")["abc"]
    assert state["ticket_used"] is True
    assert state["ticket_hash"] is None
    assert state["session_hash"] is not None
    assert state["session_hash"] != digest
    with pytest.raises(HTTPException) as error:
        handler("abc", request, None)
    assert error.value.status_code == 401
    assert client.script_calls == 1


def test_redis_cleanup_uses_ttl_not_namespace_scan():
    for path, function_name, store_name in [
        ("services/api/app/routes/instances.py", "_runtime_gateway_cleanup", "_RUNTIME_GATEWAY_SESSIONS"),
        ("services/api/app/routes/subscriptions.py", "_cleanup_static_runtime_sessions", "_STATIC_RUNTIME_SESSIONS"),
    ]:
        file = ROOT/path
        tree = ast.parse(file.read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function_name)
        ns = {"RedisSessionMap": r03.RedisSessionMap, store_name: r03.RedisSessionMap(MemoryRedis(), "static")}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(file), "exec"), ns)
        ns[function_name]()  # No time/lock/global scans touched on Redis branch.
