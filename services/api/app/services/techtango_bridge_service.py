"""B4 Pass 2: verify Techtango's independently issued Ed25519 proofs.

Proofs attest an authenticated Techtango tenant admin's control of a source tenant.
They do not make any Techtango app runnable inside AUGMIS.
"""
from __future__ import annotations

import os
import re
import time
import uuid
from functools import lru_cache
from pathlib import Path

import jwt
from tools.techtango_export_contract import ExportContractError, validated_snapshot

ISSUER = "techtango.aiappbuilder"
AUDIENCE = "augmis.control-plane.b4"
VERIFY = "techtango.tenant.verify.v1"
STAGE = "techtango.app.stage.v1"
MAX_AGE_SECONDS = 180
_JTI = re.compile(r"^[a-zA-Z0-9_-]{16,128}$")


class BridgeProofError(ValueError):
    pass


@lru_cache(maxsize=1)
def _public_key() -> bytes:
    filename = os.getenv("AUGMIS_TECHTANGO_VERIFY_KEY_FILE", "")
    if not filename:
        raise BridgeProofError("Techtango verification key is not configured")
    try:
        key = Path(filename).read_bytes()
    except OSError as exc:
        raise BridgeProofError("Techtango verification key cannot be read") from exc
    if b"BEGIN PUBLIC KEY" not in key or len(key) > 8192:
        raise BridgeProofError("Invalid Techtango public key")
    return key


def decode_bridge_proof(token: str, *, purpose: str) -> dict:
    if purpose not in {VERIFY, STAGE}:
        raise BridgeProofError("Unsupported proof purpose")
    if not isinstance(token, str) or len(token) > 48000:
        raise BridgeProofError("Malformed or oversized proof")
    try:
        claims = jwt.decode(
            token,
            _public_key(),
            algorithms=["EdDSA"],
            issuer=ISSUER,
            audience=AUDIENCE,
            options={"require": ["iss", "aud", "exp", "iat", "nbf", "jti", "purpose",
                                 "linkId", "augmisTenantId", "sourceTenantId", "actorId"]},
            leeway=5,
        )
    except jwt.PyJWTError as exc:
        raise BridgeProofError("Invalid, expired or untrusted Techtango proof") from exc
    now = int(time.time())
    iat, exp, nbf = (claims.get(k) for k in ("iat", "exp", "nbf"))
    if any(type(v) is not int for v in (iat, exp, nbf)):
        raise BridgeProofError("Invalid proof timestamps")
    if exp <= iat or exp - iat > MAX_AGE_SECONDS or iat > now + 5 or iat < now - MAX_AGE_SECONDS - 5:
        raise BridgeProofError("Proof outside permitted time window")
    if nbf > iat + 5 or nbf < iat - 5:
        raise BridgeProofError("Invalid proof activation time")
    if claims.get("purpose") != purpose:
        raise BridgeProofError("Incorrect proof purpose")
    if not isinstance(claims.get("jti"), str) or not _JTI.fullmatch(claims["jti"]):
        raise BridgeProofError("Invalid proof nonce")
    for key in ("linkId", "augmisTenantId"):
        try:
            claims[key] = str(uuid.UUID(claims[key]))
        except (TypeError, ValueError, AttributeError) as exc:
            raise BridgeProofError(f"Invalid {key}") from exc
    if type(claims.get("sourceTenantId")) is not int or claims["sourceTenantId"] < 1:
        raise BridgeProofError("Invalid source tenant")
    if type(claims.get("actorId")) is not int or claims["actorId"] < 1:
        raise BridgeProofError("Invalid proof actor")
    return claims


def check_link_claims(claims: dict, link: object) -> None:
    if (claims["linkId"] != str(link.id)
            or claims["augmisTenantId"] != str(link.augmis_tenant_id)
            or claims["sourceTenantId"] != link.external_tenant_id):
        raise BridgeProofError("Proof does not match this tenant mapping")


def validate_stage_snapshot(claims: dict) -> dict:
    raw = claims.get("snapshot")
    if not isinstance(raw, dict):
        raise BridgeProofError("Missing metadata snapshot")
    if set(raw) != {"format", "sourceTenantId", "appSlug", "appName", "fields", "sha256"}:
        raise BridgeProofError("Unexpected fields in metadata snapshot")
    if raw.get("sourceTenantId") != claims["sourceTenantId"]:
        raise BridgeProofError("Snapshot tenant mismatch")
    try:
        canonical = validated_snapshot({
            "status": "Published",
            "tenant_id": raw["sourceTenantId"],
            "app_slug": raw["appSlug"],
            "app_name": raw["appName"],
            "schema_json": {"fields": raw["fields"]},
        })
    except (ExportContractError, KeyError, TypeError, ValueError) as exc:
        raise BridgeProofError("Invalid snapshot metadata") from exc
    if raw != canonical:
        raise BridgeProofError("Snapshot digest or metadata does not match contract")
    app_id = claims.get("sourceAppId")
    if type(app_id) is not int or app_id < 1:
        raise BridgeProofError("Invalid source application ID")
    return canonical
