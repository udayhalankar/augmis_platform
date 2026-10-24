"""C1-D4 HTTP integration tests for control-plane login and revocation."""
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from services.api.app.db.base import Base
from services.api.app.db.session import get_db
from services.api.app.models.iam import User, TenantMembership, Permission, Role, RolePermission, PlatformUserRole
from services.api.app.models.platform import Tenant
from services.api.app.models.session_security import AuthSession, SessionPolicy
from services.api.app.routes import auth, session_security
from services.api.app.services.auth_service import hash_password

HEADERS = {"Origin": "http://localhost:3000", "X-Augmis-CSRF": "1"}


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__, Tenant.__table__, TenantMembership.__table__, AuthSession.__table__, SessionPolicy.__table__,
        Permission.__table__, Role.__table__, RolePermission.__table__, PlatformUserRole.__table__])
    db = Session(engine)
    user = User(id=uuid4(), email="tester@example.com", email_normalized="tester@example.com",
                first_name="Test", last_name="Person", status="active", password_hash=hash_password("TesterPass123!"))
    db.add(user); db.commit()
    monkeypatch.setattr(auth, "record_audit_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_security, "record_audit_event", lambda *args, **kwargs: None)
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(session_security.router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app, base_url="http://localhost:3000") as test:
        yield test, db, user
    db.close(); engine.dispose()


def test_cookie_login_refresh_logout_revocation(client):
    web, db, user = client
    login = web.post("/api/v1/auth/login", headers=HEADERS,
        json={"email": "tester@example.com", "password": "TesterPass123!"})
    assert login.status_code == 200, login.text
    assert "httponly" in login.headers["set-cookie"].lower()
    original = login.json()["access_token"]
    me = web.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + original})
    assert me.status_code == 200
    updated = web.post("/api/v1/auth/refresh", headers=HEADERS, json={})
    assert updated.status_code == 200, updated.text
    assert updated.json()["access_token"] != original
    status = web.get("/api/v1/auth/session", headers={"Authorization": "Bearer " + original})
    assert status.status_code == 200
    goodbye = web.post("/api/v1/auth/logout", headers=HEADERS, json={})
    assert goodbye.status_code == 200
    denied = web.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + updated.json()["access_token"]})
    assert denied.status_code == 401


def test_origin_csrf_denied(client):
    web, _, _ = client
    assert web.post("/api/v1/auth/login", json={"email":"tester@example.com","password":"TesterPass123!"}).status_code == 403
    assert web.post("/api/v1/auth/refresh", headers={"Origin":"https://evil.example", "X-Augmis-CSRF":"1"}, json={}).status_code == 403


def test_idle_activity_requires_authenticated_access(client):
    web, _, _ = client
    assert web.post("/api/v1/auth/activity", headers=HEADERS, json={}).status_code == 401


def test_administration_policy_updates_and_inheritance(client, monkeypatch):
    web, db, user = client
    monkeypatch.setattr(session_security, "require_platform_permission", lambda **kwargs: None)
    response = web.post("/api/v1/auth/login", headers=HEADERS,
        json={"email":"tester@example.com", "password":"TesterPass123!"})
    access = response.json()["access_token"]
    headers = {"Authorization": "Bearer " + access}
    overview = web.get("/api/v1/platform/session-policies", headers=headers)
    assert overview.status_code == 200
    assert overview.json()["platformDefaultMinutes"] == 30
    tenant = Tenant(id=uuid4(), name="Test Tenant", slug="test-tenant", status="active")
    db.add(tenant); db.commit()
    changed = web.put("/api/v1/platform/session-policies/tenants/" + str(tenant.id),
        headers=headers, json={"idleMinutes": 10})
    assert changed.status_code == 200
    listed = web.get("/api/v1/platform/session-policies", headers=headers).json()
    assert next(t for t in listed["tenants"] if t["id"] == str(tenant.id))["overrideMinutes"] == 10
    restored = web.delete("/api/v1/platform/session-policies/tenants/" + str(tenant.id), headers=headers)
    assert restored.status_code == 200
    assert next(t for t in web.get("/api/v1/platform/session-policies", headers=headers).json()["tenants"]
                if t["id"] == str(tenant.id))["overrideMinutes"] is None


def test_policy_admin_requires_rbac_permission(client):
    web, _, _ = client
    response = web.post("/api/v1/auth/login", headers=HEADERS,
        json={"email":"tester@example.com", "password":"TesterPass123!"})
    access = response.json()["access_token"]
    denied = web.get("/api/v1/platform/session-policies", headers={"Authorization":"Bearer " + access})
    assert denied.status_code == 403
