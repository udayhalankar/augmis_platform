"""R04 gateway resource bounds and account-scoped authentication rate control.

No network IO at import. Production rate limiting uses a dedicated Redis ACL
identity; never derive a bucket from untrusted X-Forwarded-* headers.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

# These are compatibility ceilings, not limits on Publisher AAPS ZIP uploads.
DEFAULT_GATEWAY_REQUEST_BYTES = 32 * 1024 * 1024
DEFAULT_GATEWAY_RESPONSE_BYTES = 64 * 1024 * 1024
DEFAULT_GATEWAY_SOCKET_TIMEOUT_SECONDS = 20

_AUTH_WINDOW_SECONDS = 300
_AUTH_MAX_ATTEMPTS = 20

# Redis INCR+EXPIRE must be atomic to remain consistent across worker processes.
_AUTH_RATE_LUA = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return n
"""


def is_production(env: str) -> bool:
    return str(env).strip().lower() in ("prod", "production")


async def bounded_gateway_body(request: Request, limit_bytes: int) -> bytes:
    """Bound both Content-Length and chunked body streams before buffering."""
    size_header = request.headers.get("content-length")
    if size_header is not None:
        try:
            size = int(size_header)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="R04_CONTENT_LENGTH_INVALID") from None
        if size < 0:
            raise HTTPException(status_code=400, detail="R04_CONTENT_LENGTH_INVALID")
        if size > limit_bytes:
            raise HTTPException(status_code=413, detail="R04_GATEWAY_REQUEST_TOO_LARGE")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit_bytes:
            raise HTTPException(status_code=413, detail="R04_GATEWAY_REQUEST_TOO_LARGE")
        chunks.append(chunk)
    return b"".join(chunks)


def bounded_upstream_read(upstream, limit_bytes: int) -> bytes:
    """Avoid unbounded http.client response buffering from hosted apps."""
    content_length = upstream.getheader("Content-Length")
    if content_length is not None:
        try:
            if int(content_length) > limit_bytes:
                raise HTTPException(status_code=502, detail="R04_GATEWAY_RESPONSE_TOO_LARGE")
        except ValueError:
            # Do not trust upstream Content-Length; the bounded read still applies.
            pass
    payload = upstream.read(limit_bytes + 1)
    if len(payload) > limit_bytes:
        raise HTTPException(status_code=502, detail="R04_GATEWAY_RESPONSE_TOO_LARGE")
    return payload


def enforce_login_account_rate(email: str, *, environment: str, secret: str) -> None:
    """Bound online guesses against one account across FastAPI workers.

    Global edge/WAF IP throttling is independently required because requests
    against many different usernames cannot be attributed safely behind ALB here.
    """
    if not is_production(environment):
        return  # Preserve existing development login behavior.
    url = os.environ.get("AUGMIS_ABUSE_REDIS_URL", "").strip()
    # Reuse the accepted R03 validation (TLS, nondefault ACL, authentication).
    from services.api.app.services.shared_runtime_sessions import _production_redis_url
    try:
        _production_redis_url(url)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="R04_RATE_STORE_CONFIG_INVALID") from None
    key_digest = hmac.new(secret.encode("utf-8"), email.strip().lower().encode("utf-8"), hashlib.sha256).hexdigest()
    key = "augmis:abuse:v1:login:" + key_digest
    try:
        import redis
        client = redis.Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2,
            ssl_cert_reqs="required", ssl_check_hostname=True,
        )
        count = int(client.eval(_AUTH_RATE_LUA, 1, key, _AUTH_WINDOW_SECONDS))
    except Exception:
        # Deliberately do not return to an in-memory limiter on outage.
        raise HTTPException(status_code=503, detail="R04_RATE_STORE_UNAVAILABLE") from None
    if count > _AUTH_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="R04_AUTH_RATE_LIMITED",
                            headers={"Retry-After": str(_AUTH_WINDOW_SECONDS)})
