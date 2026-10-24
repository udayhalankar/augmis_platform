"""Authoritative C1-D4 control-plane sessions. Never log raw tokens."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.core.config import settings
from services.api.app.models.iam import TenantMembership, User
from services.api.app.models.platform import Tenant
from services.api.app.models.session_security import AuthSession, SessionPolicy
from services.api.app.services.auth_service import create_access_token


class SessionDenied(Exception):
    def __init__(self, code: str, status: int = 401):
        self.code = code
        self.status = status
        super().__init__(code)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def aware_utc(value: datetime) -> datetime:
    # PostgreSQL preserves tzinfo; SQLite unit tests may return naive UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def refresh_digest(secret: str) -> str:
    # Token hashes cannot be used to recover a valid refresh credential.
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _is_same_hash(left: str | None, right: str) -> bool:
    return bool(left) and hmac.compare_digest(left, right)


def effective_idle_minutes(db: Session, user_id: uuid.UUID) -> int:
    """Most restrictive active membership policy prevents cross-tenant bypass."""
    default_record = db.get(SessionPolicy, "default")
    default_minutes = default_record.idle_minutes if default_record else settings.session_default_idle_minutes
    tenant_ids = list(db.scalars(select(TenantMembership.tenant_id).join(
        Tenant, Tenant.id == TenantMembership.tenant_id
    ).where(TenantMembership.user_id == user_id, TenantMembership.status == "active", Tenant.status == "active")))
    if not tenant_ids:
        return default_minutes
    # Each tenant's effective policy is override or platform default.
    mappings = dict(db.execute(select(SessionPolicy.tenant_id, SessionPolicy.idle_minutes).where(
        SessionPolicy.tenant_id.in_(tenant_ids)
    )).all())
    return min(mappings.get(tenant_id, default_minutes) for tenant_id in tenant_ids)


def check_session(db: Session, session: AuthSession, *, at: datetime | None = None) -> int:
    at = at or now_utc()
    if session.revoked_at is not None:
        raise SessionDenied("SESSION_REVOKED")
    if at >= aware_utc(session.absolute_expires_at):
        raise SessionDenied("SESSION_ABSOLUTE_EXPIRED")
    user = db.get(User, session.user_id)
    if user is None or user.status != "active":
        raise SessionDenied("SESSION_USER_INACTIVE")
    minutes = effective_idle_minutes(db, session.user_id)
    if at >= min(aware_utc(session.idle_expires_at),
                 aware_utc(session.last_activity_at) + timedelta(minutes=minutes)):
        raise SessionDenied("SESSION_IDLE_EXPIRED")
    return minutes


def effective_idle_deadline(db: Session, session: AuthSession) -> datetime:
    minutes = effective_idle_minutes(db, session.user_id)
    return min(aware_utc(session.idle_expires_at), aware_utc(session.last_activity_at) + timedelta(minutes=minutes))


def mint_refresh() -> str:
    return secrets.token_urlsafe(48)


def create_session(db: Session, user: User) -> tuple[AuthSession, str, str]:
    now = now_utc()
    refresh = mint_refresh()
    session = AuthSession(
        id=uuid.uuid4(), user_id=user.id, refresh_hash=refresh_digest(refresh),
        last_activity_at=now,
        idle_expires_at=now + timedelta(minutes=effective_idle_minutes(db, user.id)),
        absolute_expires_at=now + timedelta(hours=settings.session_absolute_hours),
    )
    db.add(session)
    db.flush()
    access = create_access_token(str(user.id), session_id=str(session.id))
    return session, refresh, access


def renew_session(db: Session, session_id: uuid.UUID, refresh: str) -> tuple[AuthSession, str, str]:
    # Serialize concurrent refreshes across application servers.
    session = db.scalar(select(AuthSession).where(AuthSession.id == session_id).with_for_update())
    if session is None:
        raise SessionDenied("SESSION_NOT_FOUND")
    now = now_utc()
    try:
        check_session(db, session, at=now)
    except SessionDenied as exc:
        session.revoked_at = now
        session.revoke_reason = exc.code
        db.flush()
        raise
    digest = refresh_digest(refresh)
    if not _is_same_hash(session.refresh_hash, digest):
        if _is_same_hash(session.previous_refresh_hash, digest) and session.rotated_at and (
            now - aware_utc(session.rotated_at)
        ).total_seconds() <= 5:
            # Harmless multi-tab collision: do not revoke and do not issue tokens.
            raise SessionDenied("SESSION_REFRESH_IN_PROGRESS", 409)
        session.revoked_at = now
        session.revoke_reason = "SESSION_REFRESH_REPLAY"
        db.flush()
        raise SessionDenied("SESSION_REFRESH_REPLAY")
    new_refresh = mint_refresh()
    session.previous_refresh_hash = session.refresh_hash
    session.refresh_hash = refresh_digest(new_refresh)
    session.rotated_at = now
    db.flush()
    return session, new_refresh, create_access_token(str(session.user_id), session_id=str(session.id))


def touch_session(db: Session, session: AuthSession) -> int:
    minutes = check_session(db, session)
    session.last_activity_at = now_utc()
    session.idle_expires_at = session.last_activity_at + timedelta(minutes=minutes)
    db.flush()
    return minutes


def revoke_session(db: Session, session_id: uuid.UUID, reason: str = "logout") -> None:
    session = db.scalar(select(AuthSession).where(AuthSession.id == session_id).with_for_update())
    if session is not None and session.revoked_at is None:
        session.revoked_at = now_utc()
        session.revoke_reason = reason
        db.flush()


def policy_key(tenant_id: uuid.UUID | None) -> str:
    return f"tenant:{tenant_id}" if tenant_id is not None else "default"
