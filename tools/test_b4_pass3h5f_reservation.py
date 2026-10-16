"""B4 3H-5F: fail-closed pilot reservation and activation guard tests."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from services.api.app.services import dashboard_instance_reservation as pilot

APP = uuid.UUID("09e2ccc5-9b9a-4146-9ba3-b72517e78e68")
TENANT = uuid.UUID("b6e8ccbc-aefb-4a4d-8955-1434dc1213d7")
VERSION = uuid.UUID("af0749e3-21dd-43aa-9c5a-8f01d26a3da9")


def enable(monkeypatch):
    monkeypatch.setattr(pilot.settings, "app_env", "development")
    monkeypatch.setenv(pilot.FLAG, "1")
    monkeypatch.setenv(pilot.APP_ENV, str(APP))
    monkeypatch.setenv(pilot.TENANT_ENV, str(TENANT))


def test_pilot_off_by_default(monkeypatch):
    monkeypatch.delenv(pilot.FLAG, raising=False)
    assert not pilot.is_two_phase_app(APP)
    with pytest.raises(HTTPException) as exc:
        pilot.require_pilot_scope(TENANT, APP)
    assert exc.value.status_code == 409


def test_noncanonical_identity_fails_closed(monkeypatch):
    enable(monkeypatch)
    monkeypatch.setenv(pilot.APP_ENV, str(APP).upper())
    with pytest.raises(HTTPException) as exc:
        pilot.require_pilot_scope(TENANT, APP)
    assert exc.value.status_code == 503


def test_wrong_app_and_tenant_denied(monkeypatch):
    enable(monkeypatch)
    assert pilot.is_two_phase_app(APP)
    assert not pilot.is_two_phase_app(uuid.uuid4())
    with pytest.raises(HTTPException) as exc:
        pilot.require_pilot_scope(uuid.uuid4(), APP)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        pilot.require_pilot_scope(TENANT, uuid.uuid4())
    assert exc.value.status_code == 403


def test_production_never_enabled(monkeypatch):
    enable(monkeypatch)
    monkeypatch.setattr(pilot.settings, "app_env", "production")
    with pytest.raises(HTTPException) as exc:
        pilot.require_pilot_scope(TENANT, APP)
    assert exc.value.status_code == 409


def test_draft_has_no_subscription_side_effects(monkeypatch):
    enable(monkeypatch)
    monkeypatch.setattr(pilot, "require_tenant_permission", lambda **_: None)
    monkeypatch.setattr(pilot, "require_active_subscription", lambda **_: pytest.fail("Should not read subscription for draft"))
    tenant = SimpleNamespace(id=TENANT, status="active")
    app = SimpleNamespace(id=APP, status="validated")
    version = SimpleNamespace(application_id=APP, status="image_ready", publication_status="draft")
    with pytest.raises(HTTPException) as exc:
        pilot._authorized_access(db=object(), user=object(), tenant=tenant,
                                 application=app, version=version)
    assert exc.value.status_code == 409


def test_authorization_denial_before_reservation(monkeypatch):
    enable(monkeypatch)
    from services.api.app.services.authorization_service import AuthorizationError
    monkeypatch.setattr(pilot, "require_tenant_permission",
                        lambda **_: (_ for _ in ()).throw(AuthorizationError("denied")))
    tenant = SimpleNamespace(id=TENANT, status="active")
    app = SimpleNamespace(id=APP, status="published")
    version = SimpleNamespace(application_id=APP, status="image_ready", publication_status="published")
    with pytest.raises(HTTPException) as exc:
        pilot._authorized_access(db=object(), user=object(), tenant=tenant,
                                 application=app, version=version)
    assert exc.value.status_code == 403


def test_no_subscription_denies(monkeypatch):
    enable(monkeypatch)
    from services.api.app.services.entitlement_service import EntitlementError
    monkeypatch.setattr(pilot, "require_tenant_permission", lambda **_: None)
    monkeypatch.setattr(pilot, "require_active_subscription",
                        lambda **_: (_ for _ in ()).throw(EntitlementError("no subscription")))
    tenant = SimpleNamespace(id=TENANT, status="active")
    app = SimpleNamespace(id=APP, status="published")
    version = SimpleNamespace(application_id=APP, status="image_ready", publication_status="published")
    with pytest.raises(HTTPException) as exc:
        pilot._authorized_access(db=object(), user=object(), tenant=tenant,
                                 application=app, version=version)
    assert exc.value.status_code == 403


def test_missing_instance_never_activates(monkeypatch):
    enable(monkeypatch)
    db = SimpleNamespace(get=lambda *_: None)
    with pytest.raises(HTTPException) as exc:
        pilot.activate_reserved_dashboard(db=db, instance_id=uuid.uuid4(), user=object())
    assert exc.value.status_code == 404


def test_route_contract_and_legacy_guard():
    from services.api.app.routes import instances
    paths = {(r.path, tuple(sorted(r.methods or []))) for r in instances.router.routes}
    assert ("/api/v1/tenants/{tenant_id}/application-versions/{version_id}/reserve", ("POST",)) in paths
    assert ("/api/v1/instances/{instance_id}/activate-reserved", ("POST",)) in paths
    assert ("/api/v1/instances/{instance_id}/cancel-reservation", ("POST",)) in paths
    import inspect
    src = inspect.getsource(instances.deploy_application)
    assert "is_two_phase_app(application.id)" in src
