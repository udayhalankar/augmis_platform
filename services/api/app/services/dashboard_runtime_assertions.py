"""B4 Pass 3G: opt-in, single-tenant dashboard request assertions.

Only the existing authenticated container gateway may call this module after
_get_runtime_gateway_context has revalidated tenant membership, entitlement,
launch epoch, running deployment and version policy. Never accept tenant IDs,
instance IDs or signing material from the incoming HTTP request.

This pilot deliberately binds ONE AUGMIS tenant + application ID. It is not a
multi-tenant general-purpose assertion issuer or a substitute for B3 gates.
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ISSUER = "augmis.control-plane"
TOKEN_KIND = "augmis.runtime.request.v1"
ASSERTION_HEADER = "X-Augmis-Runtime-Assertion"
TTL_SECONDS = 20  # Pass 3F verifier rejects tokens older than 30 seconds.

# Only one tenant/application pair may participate in this initial pilot.
_TENANT_ENV = "AUGMIS_DASHBOARD_ASSERTION_TENANT_ID"
_APPLICATION_ENV = "AUGMIS_DASHBOARD_ASSERTION_APPLICATION_ID"
_PRIVATE_KEY_ENV = "AUGMIS_DASHBOARD_ASSERTION_PRIVATE_KEY_FILE"


class AssertionIssuanceError(Exception):
    """Fail-closed pilot configuration/identity error with an HTTP status."""

    def __init__(self, status_code: int = 503):
        self.status_code = status_code
        super().__init__("Dashboard runtime assertion unavailable")


def _configured_uuid(name: str) -> uuid.UUID | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        parsed = uuid.UUID(raw)
    except (AttributeError, ValueError) as exc:
        raise AssertionIssuanceError() from exc
    if str(parsed) != raw:
        raise AssertionIssuanceError()
    return parsed


def _signing_key() -> Ed25519PrivateKey:
    path = os.environ.get(_PRIVATE_KEY_ENV, "").strip()
    if not path:
        raise AssertionIssuanceError()
    try:
        material = Path(path).read_bytes()
        key = serialization.load_pem_private_key(material, password=None)
    except (OSError, ValueError, TypeError) as exc:
        raise AssertionIssuanceError() from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise AssertionIssuanceError()
    return key


def make_dashboard_request_assertion(
    *,
    context: dict,
    method: str,
    relative_path: str,
    now: int | None = None,
) -> str | None:
    """Return signed JWT for an authorized dashboard GET, else None.

    The caller supplies ONLY the previously authorized backend gateway context.
    Refuse a wrong-tenant request for the opted-in application. A key must be
    available when the configured app is accessed, with no unsigned fallback.
    """
    if method != "GET" or relative_path.strip("/") != "api/dashboard":
        return None

    app_id = context["application"].id
    tenant_id = context["tenant"].id
    instance_id = context["instance"].id
    user_id = context["user"].id

    configured_app = _configured_uuid(_APPLICATION_ENV)
    if configured_app is None or configured_app != app_id:
        return None  # Unrelated existing apps continue unchanged.

    configured_tenant = _configured_uuid(_TENANT_ENV)
    if configured_tenant is None:
        raise AssertionIssuanceError()
    if configured_tenant != tenant_id:
        raise AssertionIssuanceError(403)

    key = _signing_key()
    issued = int(time.time()) if now is None else int(now)
    claims = {
        "iss": ISSUER,
        "aud": f"augmis.runtime:{instance_id}",
        "sub": str(user_id),
        "iat": issued,
        "nbf": issued,
        "exp": issued + TTL_SECONDS,
        "jti": str(uuid.uuid4()),
        "typ": TOKEN_KIND,
        "tenantId": str(tenant_id),
        "applicationId": str(app_id),
        "instanceId": str(instance_id),
        "scope": ["dashboard.read"],
    }
    return jwt.encode(claims, key, algorithm="EdDSA", headers={"typ": "JWT"})


def should_forward_request_header(name: str, hop_headers: set[str]) -> bool:
    """Strip all spoofable gateway identity/assertion headers from clients."""
    lower = name.lower()
    return (lower not in hop_headers
            and lower not in {"host", "cookie", "authorization", "content-length", "accept-encoding"}
            and not lower.startswith("x-augmis-"))


def should_forward_response_header(name: str, hop_headers: set[str]) -> bool:
    """Never reflect any identity or assertion header supplied by a container."""
    lower = name.lower()
    return (lower not in hop_headers
            and lower not in {"content-length", "set-cookie"}
            and not lower.startswith("x-augmis-"))
