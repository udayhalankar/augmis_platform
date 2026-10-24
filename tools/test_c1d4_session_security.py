"""C1-D4 isolated security regressions. Use PostgreSQL integration tests before live acceptance."""
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from services.api.app.db.base import Base
from services.api.app.models.iam import User, TenantMembership
from services.api.app.models.platform import Tenant
from services.api.app.models.session_security import AuthSession, SessionPolicy
from services.api.app.services import session_security as sec


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__, Tenant.__table__, TenantMembership.__table__, SessionPolicy.__table__, AuthSession.__table__])
    with Session(engine) as session:
        yield session
    engine.dispose()


def user(db):
    person = User(id=uuid4(), email="tester@example.test", email_normalized="tester@example.test",
                  password_hash="not-used", first_name="Test", last_name="Person", status="active")
    db.add(person); db.flush()
    return person


def test_refresh_rotates_and_replay_revokes(db, monkeypatch):
    u = user(db)
    clock = sec.now_utc()
    monkeypatch.setattr(sec, "now_utc", lambda: clock)
    auth, first, access = sec.create_session(db, u)
    assert access
    auth, second, updated = sec.renew_session(db, auth.id, first)
    assert first != second and updated != access
    with pytest.raises(sec.SessionDenied) as race:
        sec.renew_session(db, auth.id, first)
    assert race.value.status == 409
    monkeypatch.setattr(sec, "now_utc", lambda: clock + timedelta(seconds=8))
    with pytest.raises(sec.SessionDenied) as replay:
        sec.renew_session(db, auth.id, first)
    assert replay.value.code == "SESSION_REFRESH_REPLAY"
    assert auth.revoked_at is not None


def test_idle_expiration_even_when_refresh_attempted(db, monkeypatch):
    u = user(db)
    instant = sec.now_utc()
    monkeypatch.setattr(sec, "now_utc", lambda: instant)
    auth, refresh, _ = sec.create_session(db, u)
    monkeypatch.setattr(sec, "now_utc", lambda: instant + timedelta(minutes=31))
    with pytest.raises(sec.SessionDenied) as error:
        sec.renew_session(db, auth.id, refresh)
    assert error.value.code == "SESSION_IDLE_EXPIRED"


def test_passive_validation_never_updates_activity(db, monkeypatch):
    u = user(db)
    instant = sec.now_utc()
    monkeypatch.setattr(sec, "now_utc", lambda: instant)
    auth, _, _ = sec.create_session(db, u)
    monkeypatch.setattr(sec, "now_utc", lambda: instant + timedelta(minutes=9))
    sec.check_session(db, auth)
    assert auth.last_activity_at == instant
    sec.touch_session(db, auth)
    assert auth.last_activity_at == instant + timedelta(minutes=9)


def test_tenant_policy_strictest_and_default(db):
    u = user(db)
    tenants = [Tenant(id=uuid4(), name=f"Tenant {i}", slug=f"tenant-{i}", status="active") for i in range(2)]
    db.add_all(tenants); db.flush()
    db.add_all([TenantMembership(user_id=u.id, tenant_id=t.id, status="active") for t in tenants])
    db.add(SessionPolicy(policy_key="tenant:" + str(tenants[0].id), tenant_id=tenants[0].id, idle_minutes=10))
    db.add(SessionPolicy(policy_key="tenant:" + str(tenants[1].id), tenant_id=tenants[1].id, idle_minutes=30))
    db.flush()
    assert sec.effective_idle_minutes(db, u.id) == 10
    db.add(SessionPolicy(policy_key="default", idle_minutes=60))
    db.flush()
    assert sec.effective_idle_minutes(db, u.id) == 10


def test_revoked_or_suspended_session_denied(db):
    u = user(db)
    auth, _, _ = sec.create_session(db, u)
    sec.revoke_session(db, auth.id)
    with pytest.raises(sec.SessionDenied): sec.check_session(db, auth)
    auth.revoked_at = None
    u.status = "suspended"
    with pytest.raises(sec.SessionDenied): sec.check_session(db, auth)


def test_expired_idle_deadline_not_revived_by_policy_increase(db, monkeypatch):
    u = user(db)
    instant = sec.now_utc()
    monkeypatch.setattr(sec, "now_utc", lambda: instant)
    db.add(SessionPolicy(policy_key="default", idle_minutes=5))
    db.flush()
    auth, _, _ = sec.create_session(db, u)
    db.get(SessionPolicy, "default").idle_minutes = 120
    db.flush()
    monkeypatch.setattr(sec, "now_utc", lambda: instant + timedelta(minutes=6))
    with pytest.raises(sec.SessionDenied) as error:
        sec.check_session(db, auth)
    assert error.value.code == "SESSION_IDLE_EXPIRED"


def test_active_session_can_renew_beyond_old_jwt_ttl(db, monkeypatch):
    u = user(db)
    instant = sec.now_utc()
    monkeypatch.setattr(sec, "now_utc", lambda: instant)
    auth, refresh, _ = sec.create_session(db, u)
    for minute in (20, 40, 59, 65):
        monkeypatch.setattr(sec, "now_utc", lambda minute=minute: instant + timedelta(minutes=minute))
        sec.touch_session(db, auth)
    auth, new_refresh, token = sec.renew_session(db, auth.id, refresh)
    assert new_refresh != refresh
    assert token
    assert auth.revoked_at is None
