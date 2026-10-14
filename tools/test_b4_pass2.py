"""Pure proof and metadata validation tests; requires no running databases."""
import json
import time
import uuid
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from services.api.app.services.techtango_bridge_service import (
    AUDIENCE, ISSUER, STAGE, VERIFY, BridgeProofError,
    check_link_claims, decode_bridge_proof, validate_stage_snapshot, _public_key,
)
from tools.techtango_export_contract import validated_snapshot


def _proof(monkeypatch, tmp_path, purpose=VERIFY, **overrides):
    key = Ed25519PrivateKey.generate()
    pub = tmp_path / "bridge.pub"
    pub.write_bytes(key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    monkeypatch.setenv("AUGMIS_TECHTANGO_VERIFY_KEY_FILE", str(pub))
    _public_key.cache_clear()
    now = int(time.time())
    claims = dict(iss=ISSUER, aud=AUDIENCE, iat=now, nbf=now, exp=now + 120,
                  jti="unique_nonce_" + uuid.uuid4().hex, purpose=purpose,
                  linkId=str(uuid.uuid4()), augmisTenantId=str(uuid.uuid4()),
                  sourceTenantId=1, actorId=7)
    if purpose == STAGE:
        claims["sourceAppId"] = 39
        claims["snapshot"] = validated_snapshot({
            "status": "Published", "tenant_id": 1,
            "app_slug": "21augdashboard", "app_name": "Test App",
            "schema_json": {"fields": [{"name": "serial", "type": "text", "label": "Serial"}]},
        })
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="EdDSA"), claims, key


def test_valid_tenant_proof(monkeypatch, tmp_path):
    token, expected, _ = _proof(monkeypatch, tmp_path)
    assert decode_bridge_proof(token, purpose=VERIFY)["jti"] == expected["jti"]
    class Link: pass
    link = Link()
    link.id = uuid.UUID(expected["linkId"])
    link.augmis_tenant_id = uuid.UUID(expected["augmisTenantId"])
    link.external_tenant_id = expected["sourceTenantId"]
    check_link_claims(expected, link)
    link.external_tenant_id = 2
    with pytest.raises(BridgeProofError):
        check_link_claims(expected, link)


def test_expired_tampered_wrong_audience(monkeypatch, tmp_path):
    for kwargs in [dict(exp=int(time.time()) - 10), dict(aud="wrong.audience")]:
        token, _, _ = _proof(monkeypatch, tmp_path, **kwargs)
        with pytest.raises(BridgeProofError):
            decode_bridge_proof(token, purpose=VERIFY)
    token, _, _ = _proof(monkeypatch, tmp_path)
    altered = token[:-3] + ("AAA" if token[-3:] != "AAA" else "BBB")
    with pytest.raises(BridgeProofError):
        decode_bridge_proof(altered, purpose=VERIFY)


def test_wrong_purpose_and_overlong_ttl(monkeypatch, tmp_path):
    token, _, _ = _proof(monkeypatch, tmp_path, purpose=VERIFY)
    with pytest.raises(BridgeProofError):
        decode_bridge_proof(token, purpose=STAGE)
    token, _, _ = _proof(monkeypatch, tmp_path, exp=int(time.time()) + 250)
    with pytest.raises(BridgeProofError):
        decode_bridge_proof(token, purpose=VERIFY)


def test_snapshot_rejects_extra_fields_and_digest_mismatch(monkeypatch, tmp_path):
    token, _, _ = _proof(monkeypatch, tmp_path, purpose=STAGE)
    raw = decode_bridge_proof(token, purpose=STAGE)
    assert validate_stage_snapshot(raw)["sha256"] == raw["snapshot"]["sha256"]
    raw["snapshot"] = {**raw["snapshot"], "records": [{"secret": 1}]}
    with pytest.raises(BridgeProofError):
        validate_stage_snapshot(raw)
    raw["snapshot"].pop("records")
    raw["snapshot"]["sha256"] = "0" * 64
    with pytest.raises(BridgeProofError):
        validate_stage_snapshot(raw)
