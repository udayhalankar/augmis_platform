"""AUGMIS runtime assertion verification for generated single-worker FastAPI images.

Packaged in the generated AAPS image, not part of the control-plane API.
Uses the existing C1-B4 Ed25519 request-bound assertion contract and development
single-worker replay strategy demonstrated by augmis-crud-reference-v1.2.0.
The relay forwards assertions but is not a verifier.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
import uuid
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from starlette.responses import JSONResponse


class AugmisRuntimeGuard:
    """Fail-closed ASGI middleware for all /api/* requests.

    The generated Dockerfile runs exactly ONE uvicorn worker. A multi-process
    runtime requires a shared atomic replay store and is not supported here.
    """

    def __init__(self, app):
        self.app = app
        self.claim_ids = {}
        self.lock = threading.Lock()
        self.identity = {}
        for env, claim in (
            ("APP_TENANT_ID", "tenantId"),
            ("AUGMIS_RUNTIME_APPLICATION_ID", "applicationId"),
            ("AUGMIS_RUNTIME_INSTANCE_ID", "instanceId"),
        ):
            raw = os.environ.get(env, "")
            try:
                if str(uuid.UUID(raw)) != raw:
                    raise ValueError("Noncanonical UUID")
            except (ValueError, TypeError) as exc:
                raise RuntimeError("AUGMIS runtime identity not configured") from exc
            self.identity[claim] = raw
        filename = os.environ.get("AUGMIS_RUNTIME_ASSERTION_PUBLIC_KEY_FILE", "")
        if not filename or not Path(filename).is_file():
            raise RuntimeError("AUGMIS verifier public key unavailable")
        try:
            verifier = serialization.load_pem_public_key(Path(filename).read_bytes())
        except (ValueError, OSError) as exc:
            raise RuntimeError("AUGMIS verifier public key invalid") from exc
        if not isinstance(verifier, Ed25519PublicKey):
            raise RuntimeError("AUGMIS Ed25519 verifier required")
        self.verifier = verifier

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            return await self.app(scope, receive, send)

        async def reject(status: int, detail: str):
            await JSONResponse({"detail": detail}, status_code=status, headers={"Cache-Control": "no-store"})(
                scope, receive, send
            )

        tokens = [v for k, v in scope.get("headers", []) if k.lower() == b"x-augmis-runtime-assertion"]
        if len(tokens) != 1 or not tokens[0] or len(tokens[0]) > 8192:
            return await reject(401, "Signed AUGMIS runtime request required")
        try:
            token = tokens[0].decode("ascii")
        except UnicodeError:
            return await reject(401, "Invalid AUGMIS runtime request")

        # Bound the body before validating the SHA claim or handing it to FastAPI.
        pieces = []
        size = 0
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                return await reject(400, "Invalid HTTP request body")
            part = message.get("body", b"")
            size += len(part)
            if size > 1_048_576:
                return await reject(413, "Request body exceeds AUGMIS limit")
            pieces.append(part)
            if not message.get("more_body", False):
                break
        body = b"".join(pieces)

        try:
            claims = jwt.decode(
                token, self.verifier, algorithms=["EdDSA"],
                audience=f"augmis.runtime:{self.identity['instanceId']}",
                issuer="augmis.control-plane",
                options={"require": ["exp", "iat", "nbf", "jti", "iss", "aud", "sub"]},
                leeway=2,
            )
        except (jwt.PyJWTError, ValueError, TypeError):
            return await reject(401, "Invalid AUGMIS runtime request")

        method = scope["method"]
        expected_scope = "records.read" if method == "GET" else "records.write"
        route = scope.get("path", "")
        query = scope.get("query_string", b"")
        permissions = claims.get("scope")
        if (claims.get("typ") != "augmis.runtime.crud.v1"
                or any(claims.get(k) != v for k, v in self.identity.items())
                or claims.get("method") != method
                or claims.get("path") != route
                or not isinstance(permissions, list)
                or expected_scope not in permissions
                or claims.get("bodySha256") != hashlib.sha256(body).hexdigest()
                or claims.get("querySha256") != hashlib.sha256(query).hexdigest()):
            return await reject(403, "Runtime request scope mismatch")
        jti = claims.get("jti")
        if not isinstance(jti, str) or not jti or len(jti) > 128:
            return await reject(401, "Invalid AUGMIS runtime request")
        with self.lock:
            now = time.time()
            for key, expiry in list(self.claim_ids.items()):
                if expiry < now:
                    self.claim_ids.pop(key, None)
            replay = jti in self.claim_ids or len(self.claim_ids) >= 10000
            if not replay:
                self.claim_ids[jti] = float(claims["exp"]) + 2
        if replay:
            return await reject(401, "Replayed AUGMIS runtime request")

        first = True

        async def replay_body():
            nonlocal first
            if first:
                first = False
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        return await self.app(scope, replay_body, send)
