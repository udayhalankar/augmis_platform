import secrets

from datetime import (
    datetime,
    timedelta,
    timezone
)

import jwt

from pwdlib import PasswordHash

from services.api.app.core.config import settings


password_hasher = PasswordHash.recommended()


def normalize_email(
    email: str
) -> str:

    return email.strip().lower()


def hash_password(
    password: str
) -> str:

    return password_hasher.hash(
        password
    )


def verify_password(
    password: str,
    password_hash: str
) -> bool:

    return password_hasher.verify(
        password,
        password_hash
    )


def create_access_token(
    user_id: str, *, session_id: str
) -> str:

    now = datetime.now(
        timezone.utc
    )

    expiry = now + timedelta(
        minutes=settings.session_access_minutes
    )

    payload = {
        "sub": user_id,
        "sid": session_id,
        "jti": secrets.token_urlsafe(16),
        "iat": now,
        "exp": expiry,
        "type": "access"
    }

    return jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm
    )


def decode_access_token(
    token: str
) -> dict:

    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[
            settings.jwt_algorithm
        ]
    )