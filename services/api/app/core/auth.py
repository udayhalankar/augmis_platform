import uuid

import jwt

from fastapi import (
    Depends,
    HTTPException,
    status
)

from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer
)

from sqlalchemy.orm import Session

from services.api.app.db.session import get_db

from services.api.app.models.iam import User

from services.api.app.services.auth_service import (
    decode_access_token
)


bearer_scheme = HTTPBearer(
    auto_error=False
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials
        | None = Depends(bearer_scheme),

    db: Session = Depends(get_db)
) -> User:

    if not credentials:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )

    try:

        payload = decode_access_token(
            credentials.credentials
        )

        if payload.get("type") != "access":

            raise ValueError(
                "Invalid token type"
            )

        user_id = uuid.UUID(
            payload["sub"]
        )

    except (
        jwt.InvalidTokenError,
        ValueError,
        KeyError
    ):

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token"
        )

    user = db.get(
        User,
        user_id
    )

    if not user:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists"
        )

    if user.status != "active":

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not active"
        )

    return user