"""Shared AUGMIS runtime session map (optional Redis, fail closed when configured).

Only hashed tickets/cookies are stored. Redis is needed for multi-worker runtime
sessions; the in-memory option is deliberately development-only.
"""
from __future__ import annotations
import json
import os
from services.api.app.core.config import settings
import time
import uuid
from collections.abc import MutableMapping

_ID_KEYS = frozenset({"user_id", "tenant_id", "application_id", "instance_id", "subscription_id", "version_id"})


def shared_session_map(purpose: str):
    mode = os.environ.get("AUGMIS_SESSION_STORE", "memory").strip().lower()
    if mode == "memory":
        if str(settings.app_env).lower() in ("production", "prod"):
            raise RuntimeError("Production runtime requires AUGMIS_SESSION_STORE=redis")
        return {}
    if mode != "redis":
        raise RuntimeError("Unsupported AUGMIS_SESSION_STORE")
    url = os.environ.get("AUGMIS_SESSION_REDIS_URL", "").strip()
    if not url or not (url.startswith("redis://") or url.startswith("rediss://")):
        raise RuntimeError("AUGMIS_SESSION_REDIS_URL must be a Redis URL")
    import redis
    client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=3, socket_timeout=3)
    client.ping()  # No fallback to memory on failures.
    return RedisSessionMap(client, purpose)


_LUA_CONSUME = """
local raw = redis.call('GET', KEYS[1])
if not raw then return 0 end
local doc = cjson.decode(raw)
if doc.ticket_used or tonumber(doc.ticket_expires_at or 0) <= tonumber(ARGV[2]) then return 0 end
local target = ARGV[4] == 'static' and 'ticket_hash' or 'session_hash'
if doc[target] ~= ARGV[1] then return 0 end
doc.ticket_used = true
if ARGV[4] == 'static' then
    doc.ticket_hash = cjson.null
    doc.ticket_expires_at = 0
    doc.session_hash = ARGV[3]
end
redis.call('SET', KEYS[1], cjson.encode(doc), 'KEEPTTL')
return 1
"""


class RedisSessionMap(MutableMapping):
    def __init__(self, client, purpose: str):
        if purpose not in ("container", "static"):
            raise ValueError("Unsupported runtime session purpose")
        self.client = client
        self.prefix = f"augmis:runtime:v1:{purpose}:"
        self.purpose = purpose

    def _key(self, key):
        if not isinstance(key, str) or not key or len(key) > 160 or not all(c.isalnum() or c in "_-" for c in key):
            raise ValueError("Invalid session identifier")
        return self.prefix + key

    @staticmethod
    def _encode(value):
        return json.dumps(value, default=str, separators=(",", ":"))

    @staticmethod
    def _decode(raw):
        data = json.loads(raw)
        for field in _ID_KEYS.intersection(data):
            if data[field] is not None:
                data[field] = uuid.UUID(str(data[field]))
        return data

    def __getitem__(self, key):
        raw = self.client.get(self._key(key))
        if raw is None:
            raise KeyError(key)
        return self._decode(raw)

    def __setitem__(self, key, value):
        ttl = int(float(value.get("expires_at", 0)) - time.time())
        if ttl <= 0:
            raise ValueError("Refusing to persist expired runtime session")
        self.client.set(self._key(key), self._encode(value), ex=ttl)

    def __delitem__(self, key):
        if not self.client.delete(self._key(key)):
            raise KeyError(key)

    def __iter__(self):
        for key in self.client.scan_iter(match=self.prefix + "*", count=100):
            yield key[len(self.prefix):]

    def __len__(self):
        return sum(1 for _ in self.__iter__())

    def pop(self, key, default=None):
        try:
            value = self[key]
        except KeyError:
            return default
        self.client.delete(self._key(key))
        return value

    def consume_ticket(self, key: str, *, expected_hash: str, now: float, new_session_hash: str = "") -> bool:
        return bool(self.client.eval(_LUA_CONSUME, 1, self._key(key), expected_hash,
                                     str(now), new_session_hash, self.purpose))
