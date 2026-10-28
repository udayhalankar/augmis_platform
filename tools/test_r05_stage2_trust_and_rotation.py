"""R05 Stage 2 isolated tests with synthetic keys; never touch Docker, Redis, DB."""
from __future__ import annotations

import importlib
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from cryptography.fernet import Fernet, MultiFernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.api.app.services.dashboard_runtime_assertions import make_dashboard_request_assertion, AssertionIssuanceError
from tools.r05_rotate_email_credential import prepare_ciphertext, RotationDenied


def _runtime_verifier(monkeypatch):
    root = os.environ.get("AUGMIS_PASS3F_PATH", "")
    if not root or not (Path(root) / "runtime" / "security.py").is_file():
        pytest.fail("R05 Stage 2 requires AUGMIS_PASS3F_PATH pointing to the verified B4 runtime aaps_source")
    monkeypatch.syspath_prepend(root)
    # Must import the actual supplied standalone runtime verifier, not a mock.
    module = importlib.import_module("runtime.security")
    assert Path(module.__file__).resolve() == (Path(root) / "runtime" / "security.py").resolve()
    return module


def _material(tmp_path, name):
    private = Ed25519PrivateKey.generate()
    priv = tmp_path / (name + ".priv.pem")
    pub = tmp_path / (name + ".pub.pem")
    priv.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    pub.write_bytes(private.public_key().public_bytes(serialization.Encoding.PEM,
                                                      serialization.PublicFormat.SubjectPublicKeyInfo))
    return private, priv, pub


def _context():
    ids = [uuid.uuid4() for _ in range(4)]
    obj = [SimpleNamespace(id=val) for val in ids]
    return dict(zip(("tenant", "application", "instance", "user"), obj)), ids


def test_dashboard_old_and_new_trust_then_revocation(tmp_path, monkeypatch):
    verifier = _runtime_verifier(monkeypatch)
    old, old_file, old_public = _material(tmp_path, "old")
    new, new_file, new_public = _material(tmp_path, "new")
    context, (tenant, app, instance, user) = _context()
    monkeypatch.setenv("AUGMIS_DASHBOARD_ASSERTION_TENANT_ID", str(tenant))
    monkeypatch.setenv("AUGMIS_DASHBOARD_ASSERTION_APPLICATION_ID", str(app))
    monkeypatch.setenv("AUGMIS_DASHBOARD_ASSERTION_PRIVATE_KEY_FILE", str(old_file))
    monkeypatch.delenv("AUGMIS_DASHBOARD_ASSERTION_SIGNING_KEY_ID", raising=False)
    old_token = make_dashboard_request_assertion(context=context, method="GET", relative_path="api/dashboard")
    binding = verifier.RuntimeBinding(tenant, app, instance, old_public,
                                      alternate_verification_public_key_file=new_public, alternate_key_id="new-2026")
    assert verifier.validate_assertion(old_token, binding)["tenantId"] == str(tenant)
    monkeypatch.setenv("AUGMIS_DASHBOARD_ASSERTION_PRIVATE_KEY_FILE", str(new_file))
    monkeypatch.setenv("AUGMIS_DASHBOARD_ASSERTION_SIGNING_KEY_ID", "new-2026")
    new_token = make_dashboard_request_assertion(context=context, method="GET", relative_path="api/dashboard")
    assert jwt.get_unverified_header(new_token)["kid"] == "new-2026"
    assert verifier.validate_assertion(new_token, binding)["instanceId"] == str(instance)
    final_binding = verifier.RuntimeBinding(tenant, app, instance, new_public,
                                            primary_key_id="new-2026", accept_legacy_keyless=False)
    assert verifier.validate_assertion(new_token, final_binding)
    with pytest.raises(verifier.AssertionRejected):
        verifier.validate_assertion(old_token, final_binding)
    with pytest.raises(verifier.AssertionRejected):
        verifier.validate_assertion(new_token, verifier.RuntimeBinding(tenant, app, instance, old_public))


def test_unknown_kid_never_downloads_key(tmp_path, monkeypatch):
    verifier = _runtime_verifier(monkeypatch)
    key, priv, pub = _material(tmp_path, "trusted")
    context, (tenant, app, instance, _) = _context()
    monkeypatch.setenv("AUGMIS_DASHBOARD_ASSERTION_TENANT_ID", str(tenant))
    monkeypatch.setenv("AUGMIS_DASHBOARD_ASSERTION_APPLICATION_ID", str(app))
    monkeypatch.setenv("AUGMIS_DASHBOARD_ASSERTION_PRIVATE_KEY_FILE", str(priv))
    monkeypatch.setenv("AUGMIS_DASHBOARD_ASSERTION_SIGNING_KEY_ID", "unknown")
    token = make_dashboard_request_assertion(context=context, method="GET", relative_path="api/dashboard")
    binding = verifier.RuntimeBinding(tenant, app, instance, pub, primary_key_id="trusted",
                                      accept_legacy_keyless=False)
    with pytest.raises(verifier.AssertionRejected):
        verifier.validate_assertion(token, binding)
    monkeypatch.setenv("AUGMIS_DASHBOARD_ASSERTION_SIGNING_KEY_ID", "bad/../kid")
    with pytest.raises(AssertionIssuanceError):
        make_dashboard_request_assertion(context=context, method="GET", relative_path="api/dashboard")


def test_corrupted_extra_public_key_fails_startup(tmp_path, monkeypatch):
    verifier = _runtime_verifier(monkeypatch)
    _, _, pub = _material(tmp_path,"real")
    broken = tmp_path / "broken.pem"
    broken.write_text("not-pem")
    binding = verifier.RuntimeBinding(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), pub,
        alternate_key_id="next", alternate_verification_public_key_file=broken)
    with pytest.raises(RuntimeError, match="unavailable"):
        binding.validate_key_configuration()


def test_email_credential_can_rotate_with_new_key_only():
    old = Fernet.generate_key()
    new = Fernet.generate_key()
    original = Fernet(old).encrypt(b"synthetic-smtp-credential").decode()
    candidate = prepare_ciphertext(original, keyring=MultiFernet([Fernet(new), Fernet(old)]), active=Fernet(new))
    assert candidate != original
    assert Fernet(new).decrypt(candidate.encode()) == b"synthetic-smtp-credential"
    assert prepare_ciphertext(candidate, keyring=MultiFernet([Fernet(new)]), active=Fernet(new)) is None
    with pytest.raises(RotationDenied, match="R05_CREDENTIAL_KEYRING_DENIED"):
        prepare_ciphertext(original, keyring=MultiFernet([Fernet(new)]), active=Fernet(new))


def test_dashboard_mount_contract_preloads_next_trust_key(tmp_path, monkeypatch):
    from services.api.app.services.dashboard_runtime_mounts import build_dashboard_pilot_launch
    primary, primary_priv, primary_pub = _material(tmp_path, "primary")
    replacement, replacement_priv, replacement_pub = _material(tmp_path, "replacement")
    tenant, app, instance = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    root = tmp_path / "secret-root"
    target = root / str(tenant) / str(instance)
    target.mkdir(parents=True)
    (target / "db_password").write_text("test-db-password")
    (target / "assertion_public.pem").write_bytes(primary_pub.read_bytes())
    (target / "assertion_alternate_public.pem").write_bytes(replacement_pub.read_bytes())
    image_id = "sha256:" + "a" * 64
    values = {
        "AUGMIS_DASHBOARD_ASSERTION_APPLICATION_ID": str(app),
        "AUGMIS_DASHBOARD_ASSERTION_TENANT_ID": str(tenant),
        "AUGMIS_DASHBOARD_ASSERTION_PRIVATE_KEY_FILE": str(replacement_priv),
        "AUGMIS_DASHBOARD_ASSERTION_SIGNING_KEY_ID": "replacement-2026",
        "AUGMIS_DASHBOARD_ASSERTION_ALTERNATE_KEY_ID": "replacement-2026",
        "AUGMIS_DASHBOARD_SECRET_ROOT": str(root),
        "AUGMIS_DASHBOARD_APPROVED_IMAGE_ID": image_id,
        "AUGMIS_DASHBOARD_PRIVATE_NETWORK": "augmis-isolated-private",
        "AUGMIS_DASHBOARD_DB_HOST": "private-postgres",
    }
    for name, value in values.items():
        monkeypatch.setenv(name,value)
    def docker(args):
        if "network" in args: return "true"
        return "10001:10001"
    result = build_dashboard_pilot_launch(tenant_id=tenant, application_id=app,
                                            instance_id=instance, image_id=image_id,
                                            inspect_docker=docker)
    assert len(result.secret_mounts) == 3
    assert result.environment["AUGMIS_RUNTIME_ASSERTION_ALTERNATE_KEY_ID"] == "replacement-2026"
    assert result.environment["AUGMIS_RUNTIME_ASSERTION_ALTERNATE_PUBLIC_KEY_FILE"].startswith("/run/secrets/")
    # Mismatched signing material must fail before Docker commands are issued.
    monkeypatch.setenv("AUGMIS_DASHBOARD_ASSERTION_PRIVATE_KEY_FILE", str(primary_priv))
    with pytest.raises(Exception,match="verifier differs"):
        build_dashboard_pilot_launch(tenant_id=tenant,application_id=app,
                                     instance_id=instance,image_id=image_id,
                                     inspect_docker=docker)


def test_dashboard_mount_contract_no_unapproved_next_key(tmp_path,monkeypatch):
    from services.api.app.services.dashboard_runtime_mounts import _validate_material, PilotLaunchError
    _, priv, pub = _material(tmp_path,"first")
    _, other_priv, other_pub = _material(tmp_path,"second")
    password = tmp_path / "password"
    password.write_text("synthetic-password")
    with pytest.raises(PilotLaunchError, match="not trusted"):
        _validate_material(password,pub,str(priv),alternate_path=other_pub,
                           signing_key_id="unapproved",alternate_key_id="approved")
    with pytest.raises(PilotLaunchError, match="verifier differs"):
        _validate_material(password,pub,str(other_priv))
