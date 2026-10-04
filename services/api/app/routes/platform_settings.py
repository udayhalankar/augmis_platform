# services/api/app/routes/platform_settings.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from services.api.app.core.auth import get_current_user
from services.api.app.db.session import get_db
from services.api.app.models.iam import User
from services.api.app.schemas.platform_settings import (
    PlatformEmailSettingsResponse,
    PlatformEmailSettingsUpdate,
    PlatformEmailTestRequest,
    PlatformEmailTestResponse,
)
from services.api.app.services.audit_service import record_audit_event
from services.api.app.services.authorization_service import (
    AuthorizationError,
    require_platform_permission,
)
from services.api.app.services.email_service import (
    EmailDeliveryError,
    send_test_email,
)
from services.api.app.services.platform_settings_service import (
    PlatformSettingsError,
    get_effective_mail_configuration,
    platform_email_settings_payload,
    update_platform_email_settings,
)


router = APIRouter(
    prefix="/api/v1/platform/settings",
    tags=["Platform Settings"],
)


def _require_settings_admin(
    *,
    db: Session,
    current_user: User,
) -> None:
    try:
        require_platform_permission(
            db=db,
            user=current_user,
            permission_code="platform.settings.manage",
        )
    except AuthorizationError as error:
        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error


@router.get(
    "/email",
    response_model=PlatformEmailSettingsResponse,
)
def get_email_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_settings_admin(
        db=db,
        current_user=current_user,
    )
    return platform_email_settings_payload(db)


@router.put(
    "/email",
    response_model=PlatformEmailSettingsResponse,
)
def update_email_settings(
    payload: PlatformEmailSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_settings_admin(
        db=db,
        current_user=current_user,
    )

    try:
        row = update_platform_email_settings(
            db,
            payload=payload,
            updated_by_user_id=current_user.id,
        )

        record_audit_event(
            db,
            action="platform.settings.email.updated",
            resource_type="platform_email_settings",
            resource_id="email",
            actor_user_id=current_user.id,
            outcome="success",
            message="Platform email settings updated.",
            metadata={
                "provider": row.provider,
                "enabled": row.enabled,
                "host": row.host,
                "port": row.port,
                "fromEmail": row.from_email,
                "useStarttls": row.use_starttls,
                "useSsl": row.use_ssl,
            },
        )

        db.commit()
        return platform_email_settings_payload(db)

    except PlatformSettingsError as error:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


@router.post(
    "/email/test",
    response_model=PlatformEmailTestResponse,
)
def test_email_settings(
    payload: PlatformEmailTestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_settings_admin(
        db=db,
        current_user=current_user,
    )

    try:
        mail_config, source, provider = (
            get_effective_mail_configuration(db)
        )

        send_test_email(
            recipient_email=str(payload.recipient),
            mail_configuration=mail_config,
        )

        record_audit_event(
            db,
            action="platform.settings.email.test_sent",
            resource_type="platform_email_settings",
            resource_id="email",
            actor_user_id=current_user.id,
            outcome="success",
            message="Platform email test sent.",
            metadata={
                "recipient": str(payload.recipient),
                "provider": provider,
                "source": source,
            },
        )

        db.commit()

        return {
            "status": "sent",
            "recipient": str(payload.recipient),
            "provider": provider,
            "source": source,
        }

    except (PlatformSettingsError, EmailDeliveryError) as error:
        db.rollback()

        record_audit_event(
            db,
            action="platform.settings.email.test_failed",
            resource_type="platform_email_settings",
            resource_id="email",
            actor_user_id=current_user.id,
            outcome="failed",
            message="Platform email test failed.",
            metadata={
                "recipient": str(payload.recipient),
            },
        )
        db.commit()

        raise HTTPException(
            status_code=502,
            detail="Test email delivery failed.",
        ) from error
