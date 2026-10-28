"""Offline R07 acceptance for coordinated 'any' release upgrades.
Uses existing mocked Docker/DB harness. Never runs live Docker or modifies DB.
"""
from pathlib import Path
import pytest
from fastapi import HTTPException
from tools.test_c1d3_release_lifecycle import setup, invoke


def test_any_coordinated_release_keeps_qualification_and_promotes_baseline(monkeypatch):
    db, calls, _ = setup(monkeypatch)
    db.sub.version_policy = 'any'
    result = invoke(db)
    assert result['status'] == 'UPGRADED'
    assert db.instance.active_version_id == 'new'
    assert db.sub.baseline_version_id == 'new'
    assert calls == ['qualification', 'start', 'stop']


def test_any_unpublished_release_blocked_before_container_start(monkeypatch):
    db, calls, _ = setup(monkeypatch)
    db.sub.version_policy = 'any'
    db.target.publication_status = 'draft'
    with pytest.raises(HTTPException) as err:
        invoke(db)
    assert err.value.status_code == 409
    assert err.value.detail == 'C1D3_TARGET_NOT_PUBLISHED'
    assert calls == []


def test_any_missing_qualification_blocked_before_container_start(monkeypatch):
    db, calls, fake = setup(monkeypatch)
    db.sub.version_policy = 'any'
    class MissingQualification(ValueError):
        code = 'QUALIFICATION_REQUIRED'
    fake.QualificationGateError = MissingQualification
    def reject(*args, **kwargs):
        raise MissingQualification()
    fake.require_passing_build = reject
    with pytest.raises(HTTPException) as err:
        invoke(db)
    assert err.value.detail == 'QUALIFICATION_REQUIRED'
    assert calls == []


def test_pinned_remains_denied(monkeypatch):
    db, calls, _ = setup(monkeypatch)
    db.sub.version_policy = 'pinned'
    db.sub.pinned_version_id = 'old'
    with pytest.raises(HTTPException) as err:
        invoke(db)
    assert err.value.detail == 'C1D3_RELEASE_POLICY_NOT_SUPPORTED'
    assert calls == []


def test_release_options_same_backend_authorizes_any_without_bypassing_guards():
    import inspect
    from services.api.app.routes.instances import get_release_options
    src = inspect.getsource(get_release_options)
    assert "sub.version_policy not in ('same_major', 'any')" in src
    assert "require_subscription_version_allowed(db=db, subscription=sub, target_version=candidate)" in src
    assert 'require_passing_build(db, version=candidate)' in src
    assert "permission in ('application.deploy', 'subscription.manage')" in src
