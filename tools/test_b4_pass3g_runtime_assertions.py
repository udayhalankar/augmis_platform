"""B4 Pass 3G: gateway assertion and header-hardening unit tests.

Optional: set AUGMIS_PASS3F_PATH to the extracted B4_PASS3F_HTTP_FOUNDATION
folder to also verify tokens with the *real* Pass 3F runtime verifier.
"""
from __future__ import annotations

import importlib
import os
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.api.app.services.dashboard_runtime_assertions import (
    ASSERTION_HEADER,
    AssertionIssuanceError,
    make_dashboard_request_assertion,
    should_forward_request_header,
    should_forward_response_header,
)


def _ids():
    return dict(user=uuid.uuid4(), tenant=uuid.uuid4(), app=uuid.uuid4(), instance=uuid.uuid4())


def _context(ids):
    return {
        "user": SimpleNamespace(id=ids["user"]),
        "tenant": SimpleNamespace(id=ids["tenant"]),
        "application": SimpleNamespace(id=ids["app"]),
        "instance": SimpleNamespace(id=ids["instance"]),
    }


@pytest.fixture
def configured(monkeypatch, tmp_path):
    ids = _ids()
    key = Ed25519PrivateKey.generate()
    private = tmp_path / "private.pem"
    public = tmp_path / "public.pem"
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                    serialization.PublicFormat.SubjectPublicKeyInfo))
    monkeypatch.setenv("AUGMIS_DASHBOARD_ASSERTION_APPLICATION_ID", str(ids["app"]))
    monkeypatch.setenv("AUGMIS_DASHBOARD_ASSERTION_TENANT_ID", str(ids["tenant"]))
    monkeypatch.setenv("AUGMIS_DASHBOARD_ASSERTION_PRIVATE_KEY_FILE", str(private))
    return ids, _context(ids), key, public


def test_signed_token_fields_and_ttl(configured):
    ids, context, key, _ = configured
    token = make_dashboard_request_assertion(context=context, method="GET", relative_path="api/dashboard", now=int(time.time()))
    decoded = jwt.decode(token, key.public_key(), algorithms=["EdDSA"], issuer="augmis.control-plane",
                         audience=f"augmis.runtime:{ids['instance']}", options={"require": ["exp", "iat", "jti"]})
    assert decoded["tenantId"] == str(ids["tenant"])
    assert decoded["applicationId"] == str(ids["app"])
    assert decoded["instanceId"] == str(ids["instance"])
    assert decoded["sub"] == str(ids["user"])
    assert decoded["scope"] == ["dashboard.read"]
    assert decoded["typ"] == "augmis.runtime.request.v1"
    assert decoded["exp"] - decoded["iat"] == 20
    assert decoded["nbf"] == decoded["iat"]


def test_different_requests_have_different_jtis(configured):
    _, context, key, _ = configured
    tokens = [make_dashboard_request_assertion(context=context, method="GET", relative_path="api/dashboard") for _ in range(2)]
    claims = [jwt.decode(t, key.public_key(), algorithms=["EdDSA"], audience=f"augmis.runtime:{context['instance'].id}", issuer="augmis.control-plane") for t in tokens]
    assert claims[0]["jti"] != claims[1]["jti"]


@pytest.mark.parametrize("method,path", [
    ("HEAD", "api/dashboard"), ("POST", "api/dashboard"),
    ("GET", "api/other"), ("GET", "api/dashboard/metrics"), ("GET", ""),
])
def test_non_dashboard_get_is_unchanged(configured, method, path):
    _, context, _, _ = configured
    assert make_dashboard_request_assertion(context=context, method=method, relative_path=path) is None


def test_other_apps_do_not_receive_assertion(configured):
    ids, context, _, _ = configured
    context["application"] = SimpleNamespace(id=uuid.uuid4())
    assert make_dashboard_request_assertion(context=context, method="GET", relative_path="api/dashboard") is None


def test_target_app_wrong_tenant_is_denied(configured):
    ids, context, _, _ = configured
    context["tenant"] = SimpleNamespace(id=uuid.uuid4())
    with pytest.raises(AssertionIssuanceError) as failure:
        make_dashboard_request_assertion(context=context, method="GET", relative_path="api/dashboard")
    assert failure.value.status_code == 403


def test_target_app_no_key_is_fail_closed(configured, monkeypatch):
    _, context, _, _ = configured
    monkeypatch.delenv("AUGMIS_DASHBOARD_ASSERTION_PRIVATE_KEY_FILE")
    with pytest.raises(AssertionIssuanceError) as failure:
        make_dashboard_request_assertion(context=context, method="GET", relative_path="api/dashboard")
    assert failure.value.status_code == 503


def test_target_app_missing_tenant_config_is_fail_closed(configured, monkeypatch):
    _, context, _, _ = configured
    monkeypatch.delenv("AUGMIS_DASHBOARD_ASSERTION_TENANT_ID")
    with pytest.raises(AssertionIssuanceError):
        make_dashboard_request_assertion(context=context, method="GET", relative_path="api/dashboard")


def test_target_app_wrong_key_type_is_fail_closed(configured, monkeypatch, tmp_path):
    _, context, _, _ = configured
    bad = tmp_path / "not-key.pem"
    bad.write_text("invalid", encoding="utf-8")
    monkeypatch.setenv("AUGMIS_DASHBOARD_ASSERTION_PRIVATE_KEY_FILE", str(bad))
    with pytest.raises(AssertionIssuanceError):
        make_dashboard_request_assertion(context=context, method="GET", relative_path="api/dashboard")


def test_missing_allowlist_leaves_existing_apps_unchanged(configured, monkeypatch):
    _, context, _, _ = configured
    monkeypatch.delenv("AUGMIS_DASHBOARD_ASSERTION_APPLICATION_ID")
    assert make_dashboard_request_assertion(context=context, method="GET", relative_path="api/dashboard") is None


@pytest.mark.parametrize("key", [
    "X-Augmis-Runtime-Assertion", "x-aUGMis-tenant-id", "X-Augmis-Application-Id",
    "X-Augmis-Instance-Id", "X-Augmis-New-Identity-Claim", "Authorization", "Cookie", "Host",
])
def test_client_cannot_spoof_gateway_header(key):
    assert not should_forward_request_header(key, {"connection"})


def test_unrelated_client_headers_are_preserved():
    assert should_forward_request_header("Accept-Language", {"connection"})
    assert not should_forward_request_header("Connection", {"connection"})


def test_container_cannot_reflect_gateway_identity_or_assertion():
    assert not should_forward_response_header(ASSERTION_HEADER, set())
    assert not should_forward_response_header("x-augmis-tenant-id", set())
    assert not should_forward_response_header("Set-Cookie", set())
    assert should_forward_response_header("Content-Type", set())


def test_cross_component_pass3f_verifier(configured, monkeypatch):
    runtime_folder = os.environ.get("AUGMIS_PASS3F_PATH")
    if not runtime_folder:
        pytest.skip("Set AUGMIS_PASS3F_PATH to run end-to-end token verification")
    root = Path(runtime_folder)
    if not (root / "runtime" / "security.py").is_file():
        pytest.fail("AUGMIS_PASS3F_PATH does not contain runtime/security.py")
    monkeypatch.syspath_prepend(str(root))
    # Pass3F's security module, not a second handwritten verifier.
    runtime_security = importlib.import_module("runtime.security")
    ids, context, _, public = configured
    binding = runtime_security.RuntimeBinding(ids["tenant"], ids["app"], ids["instance"], public)
    token = make_dashboard_request_assertion(context=context, method="GET", relative_path="api/dashboard")
    verified = runtime_security.validate_assertion(token, binding)
    assert verified["tenantId"] == str(ids["tenant"])
    parts = token.split(".")
    signature = parts[2]
    parts[2] = ("A" if signature[0] != "A" else "B") + signature[1:]
    tampered = ".".join(parts)
    with pytest.raises(runtime_security.AssertionRejected):
        runtime_security.validate_assertion(tampered, binding)
    mismatched = runtime_security.RuntimeBinding(uuid.uuid4(), ids["app"], ids["instance"], public)
    with pytest.raises(runtime_security.AssertionRejected):
        runtime_security.validate_assertion(token, mismatched)
