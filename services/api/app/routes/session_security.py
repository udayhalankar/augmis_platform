"""C1-D4 authenticated session lifecycle and administrative idle policies."""
from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.core.auth import get_current_user
from services.api.app.core.config import settings, validate_production_ingress_config
from services.api.app.db.session import get_db
from services.api.app.models.iam import User
from services.api.app.models.platform import Tenant
from services.api.app.models.session_security import AuthSession, SessionPolicy
from services.api.app.services.authorization_service import AuthorizationError, require_platform_permission
from services.api.app.services.audit_service import record_audit_event
from services.api.app.services.auth_service import decode_access_token
from services.api.app.services.session_security import (
    SessionDenied, check_session, effective_idle_minutes, effective_idle_deadline, aware_utc, now_utc, policy_key,
    refresh_digest, renew_session, revoke_session, touch_session,
)
import jwt
import hmac

router = APIRouter(prefix="/api/v1", tags=["Session Security"])
COOKIE_PROD = "__Host-augmis_refresh"
COOKIE_DEV = "augmis_dev_refresh"


class IdlePolicyUpdate(BaseModel):
    idleMinutes: int = Field(ge=5, le=120)


def cookie_name() -> str:
    if settings.app_env.strip().lower() in ("production", "prod"):
        validate_production_ingress_config(settings)
        return COOKIE_PROD
    return COOKIE_DEV


def assert_origin(request: Request) -> None:
    origin = request.headers.get("origin", "")
    if settings.app_env.strip().lower() in ("production", "prod"):
        # Do not widen the session-CSRF trust boundary with CORS entries,
        # Host-derived URLs or client-supplied forwarding headers.
        expected, _ = validate_production_ingress_config(settings)
        allowed = origin == expected
    else:
        allowed = origin.rstrip("/") in (set(settings.cors_origin_list) | {settings.frontend_base_url.rstrip("/")})
    if not allowed or request.headers.get("x-augmis-csrf") != "1":
        raise HTTPException(status_code=403, detail="SESSION_ORIGIN_DENIED")


def set_cookie(response: Response, session_id: uuid.UUID, refresh: str):
    response.set_cookie(
        key=cookie_name(), value=f"{session_id}.{refresh}",
        httponly=True, secure=settings.session_cookie_secure, samesite="lax",
        path="/", max_age=settings.session_absolute_hours * 3600,
    )
    response.headers["Cache-Control"] = "no-store"


def clear_cookie(response: Response):
    response.delete_cookie(key=cookie_name(), path="/", secure=settings.session_cookie_secure, samesite="lax")
    response.headers["Cache-Control"] = "no-store"


def parse_cookie(request: Request) -> tuple[uuid.UUID, str]:
    cookie = request.cookies.get(cookie_name(), "")
    try:
        identifier, refresh = cookie.split(".", 1)
        if not refresh or len(refresh) > 300:
            raise ValueError()
        return uuid.UUID(identifier), refresh
    except (ValueError, AttributeError):
        raise HTTPException(status_code=401, detail="SESSION_REFRESH_MISSING")


def reply_session(db: Session, session: AuthSession, access: str) -> dict:
    return {
        "access_token": access, "token_type": "bearer",
        "idleMinutes": effective_idle_minutes(db, session.user_id),
        "lastActivityAt": aware_utc(session.last_activity_at).isoformat(),
        "idleDeadline": effective_idle_deadline(db, session).isoformat(),
        "absoluteDeadline": aware_utc(session.absolute_expires_at).isoformat(),
        "accessExpiresInSeconds": settings.session_access_minutes * 60,
    }


@router.post("/auth/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    assert_origin(request)
    sid, secret = parse_cookie(request)
    try:
        session, fresh, access = renew_session(db, sid, secret)
    except SessionDenied as exc:
        # Persist a replay/expiration revocation instead of rolling it back.
        db.commit()
        if exc.status != 409:
            clear_cookie(response)
        raise HTTPException(status_code=exc.status, detail=exc.code)
    answer = reply_session(db, session, access)
    db.commit()
    set_cookie(response, sid, fresh)
    return answer


@router.get("/auth/session")
def status(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # The access token is already checked by get_current_user.
    token = request.headers.get("authorization", "").removeprefix("Bearer ")
    sid = uuid.UUID(decode_access_token(token)["sid"])
    session = db.get(AuthSession, sid)
    minutes = check_session(db, session)
    return {
        "idleMinutes": minutes,
        "lastActivityAt": aware_utc(session.last_activity_at).isoformat(),
        "idleDeadline": effective_idle_deadline(db, session).isoformat(),
        "absoluteDeadline": aware_utc(session.absolute_expires_at).isoformat(),
    }


@router.post("/auth/activity")
def user_activity(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    assert_origin(request)
    token = request.headers.get("authorization", "").removeprefix("Bearer ")
    sid = uuid.UUID(decode_access_token(token)["sid"])
    session = db.scalar(select(AuthSession).where(AuthSession.id == sid).with_for_update())
    minutes = touch_session(db, session)
    db.commit()
    return {"idleMinutes": minutes, "lastActivityAt": aware_utc(session.last_activity_at).isoformat(),
        "idleDeadline": effective_idle_deadline(db, session).isoformat()}


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    assert_origin(request)
    try:
        sid, refresh = parse_cookie(request)
        session = db.scalar(select(AuthSession).where(AuthSession.id == sid).with_for_update())
        # A mismatched credential may not revoke somebody else's session.
        if session is not None and hmac.compare_digest(refresh_digest(refresh), session.refresh_hash):
            revoke_session(db, sid, reason="logout")
            record_audit_event(db, action="auth.session.revoked", resource_type="session",
                resource_id=sid, actor_user_id=session.user_id, outcome="success", message="Session logged out.")
            db.commit()
    except HTTPException:
        pass
    clear_cookie(response)
    return {"status": "logged_out"}


def require_policy_admin(db: Session, user: User) -> None:
    try:
        require_platform_permission(db=db, user=user, permission_code="platform.settings.manage")
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/platform/session-policies")
def list_policies(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_policy_admin(db, user)
    default_row = db.get(SessionPolicy, "default")
    default = default_row.idle_minutes if default_row else settings.session_default_idle_minutes
    overrides = {p.tenant_id: p for p in db.scalars(select(SessionPolicy).where(SessionPolicy.tenant_id.is_not(None)))}
    tenants = list(db.scalars(select(Tenant).order_by(Tenant.name.asc())))
    return {
        "platformDefaultMinutes": default,
        "tenants": [{"id": str(t.id), "name": t.name, "status": t.status,
                     "idleMinutes": overrides[t.id].idle_minutes if t.id in overrides else default,
                     "overrideMinutes": overrides[t.id].idle_minutes if t.id in overrides else None}
                    for t in tenants],
        "multiTenantRule": "strictest-active-membership",
    }


def save_policy(db: Session, user: User, tenant_id: uuid.UUID | None, minutes: int):
    key = policy_key(tenant_id)
    row = db.get(SessionPolicy, key)
    if row is None:
        row = SessionPolicy(policy_key=key, tenant_id=tenant_id, idle_minutes=minutes)
        db.add(row)
    row.idle_minutes = minutes
    row.updated_by = user.id
    row.updated_at = now_utc()
    record_audit_event(db, action="auth.session_policy.updated", resource_type="session_policy",
        resource_id=key, actor_user_id=user.id, tenant_id=tenant_id,
        message="Session inactivity policy updated.", metadata={"idleMinutes": minutes})
    db.commit()
    return {"idleMinutes": minutes, "policyKey": key}


@router.put("/platform/session-policies/default")
def update_default(payload: IdlePolicyUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_policy_admin(db, user)
    return save_policy(db, user, None, payload.idleMinutes)


@router.put("/platform/session-policies/tenants/{tenant_id}")
def update_tenant(tenant_id: uuid.UUID, payload: IdlePolicyUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_policy_admin(db, user)
    if db.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return save_policy(db, user, tenant_id, payload.idleMinutes)


@router.delete("/platform/session-policies/tenants/{tenant_id}")
def reset_tenant(tenant_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_policy_admin(db, user)
    row = db.get(SessionPolicy, policy_key(tenant_id))
    if row is not None:
        db.delete(row)
        record_audit_event(db, action="auth.session_policy.reset", resource_type="session_policy",
            resource_id=policy_key(tenant_id), actor_user_id=user.id, tenant_id=tenant_id,
            message="Tenant session policy reverted to platform default.")
        db.commit()
    return {"status": "inherited"}
