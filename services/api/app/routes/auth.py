# services/api/app/routes/auth.py
from fastapi import (
    APIRouter,
    Depends,
    HTTPException
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
    TokenResponse,
    UserResponse
)

from services.api.app.services.auth_service import (
    create_access_token,
    hash_password,
    normalize_email,
    verify_password
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

    db.commit()

    db.refresh(user)

    return user


@router.post(
    "/login",
    response_model=TokenResponse
)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db)
):

    normalized = normalize_email(
        str(payload.email)
    )

    user = db.scalar(
        select(User)
        .where(
            User.email_normalized
            == normalized
        )
    )

    if not user:

        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    if not verify_password(
        payload.password,
        user.password_hash
    ):

        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    if user.status != "active":

        raise HTTPException(
            status_code=403,
            detail="Account is not active"
        )

    token = create_access_token(
        str(user.id)
    )

    return TokenResponse(
        access_token=token
    )


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