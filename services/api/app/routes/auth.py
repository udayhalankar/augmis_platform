# services/api/app/routes/auth.py
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
)

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.core.auth import (
    get_current_user
)

from services.api.app.db.session import (
    get_db
)

from services.api.app.models.iam import (
    User
)

from services.api.app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    SessionTokenResponse,
    UserResponse
)

from services.api.app.services.auth_service import (
    hash_password,
    normalize_email,
    verify_password
)

from services.api.app.routes.session_security import assert_origin, set_cookie, reply_session
from services.api.app.services.session_security import create_session
from services.api.app.services.r04_abuse_controls import enforce_login_account_rate
from services.api.app.core.config import settings

from services.api.app.services.audit_service import (
    record_audit_event,
)


router = APIRouter(
    prefix="/api/v1/auth",
    tags=["Authentication"]
)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=201
)
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db)
):

    normalized = normalize_email(
        str(payload.email)
    )

    existing = db.scalar(
        select(User)
        .where(
            User.email_normalized
            == normalized
        )
    )

    if existing:

        raise HTTPException(
            status_code=409,
            detail="Email already registered"
        )

    user = User(
        email=str(payload.email),
        email_normalized=normalized,
        password_hash=hash_password(
            payload.password
        ),
        first_name=payload.first_name,
        last_name=payload.last_name,
        status="active"
    )

    db.add(user)

    db.flush()

    record_audit_event(
        db,
        action="auth.user.registered",
        resource_type="user_account",
        resource_id=user.id,
        actor_user_id=user.id,
        outcome="success",
        message="User account registered.",
        metadata={
            "email": user.email,
            "status": user.status,
        },
    )

    db.commit()

    db.refresh(user)

    return user


@router.post(
    "/login",
    response_model=SessionTokenResponse
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    assert_origin(request)

    normalized = normalize_email(
        str(payload.email)
    )

    # R04: production-only Redis-backed account throttle. No client IP trust.
    enforce_login_account_rate(
        normalized, environment=settings.app_env, secret=settings.jwt_secret
    )

    user = db.scalar(
        select(User)
        .where(
            User.email_normalized
            == normalized
        )
    )

    if not user:

        record_audit_event(
            db,
            action="auth.login.failed",
            resource_type="authentication",
            resource_id=normalized,
            outcome="failed",
            message="Login failed: invalid credentials.",
            metadata={
                "reason": "invalid_credentials",
            },
        )

        db.commit()

        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    if not verify_password(
        payload.password,
        user.password_hash
    ):

        record_audit_event(
            db,
            action="auth.login.failed",
            resource_type="user_account",
            resource_id=user.id,
            actor_user_id=user.id,
            outcome="failed",
            message="Login failed: invalid credentials.",
            metadata={
                "reason": "invalid_credentials",
            },
        )

        db.commit()

        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    if user.status != "active":

        record_audit_event(
            db,
            action="auth.login.denied",
            resource_type="user_account",
            resource_id=user.id,
            actor_user_id=user.id,
            outcome="denied",
            message="Login denied because the account is not active.",
            metadata={
                "status": user.status,
                "reason": "account_not_active",
            },
        )

        db.commit()

        raise HTTPException(
            status_code=403,
            detail="Account is not active"
        )

    session, refresh_secret, token = create_session(db, user)

    record_audit_event(
        db,
        action="auth.login.succeeded",
        resource_type="user_account",
        resource_id=user.id,
        actor_user_id=user.id,
        outcome="success",
        message="User login succeeded.",
        metadata={
            "status": user.status,
        },
    )

    db.commit()

    set_cookie(response, session.id, refresh_secret)
    return reply_session(db, session, token)


@router.get(
    "/me",
    response_model=UserResponse
)
def me(
    current_user: User = Depends(
        get_current_user
    )
):

    return current_user