# services/api/app/routes/webhooks.py

from __future__ import annotations

import json

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)

from sqlalchemy.orm import Session

from svix.webhooks import Webhook

from services.api.app.core.config import (
    settings,
)

from services.api.app.db.session import (
    get_db,
)

from services.api.app.services.email_delivery_service import (
    process_resend_webhook,
)


router = APIRouter(
    prefix="/api/v1/webhooks",
    tags=["Webhooks"],
)


def _required_header(
    request: Request,
    *names: str,
) -> str:

    for name in names:

        value = request.headers.get(
            name
        )

        if value:
            return value

    raise HTTPException(
        status_code=400,
        detail=(
            "Missing webhook "
            "signature header."
        ),
    )


@router.post(
    "/resend",
)
async def receive_resend_webhook(
    request: Request,
    db: Session = Depends(
        get_db
    ),
):

    secret = str(
        settings.resend_webhook_secret
        or ""
    ).strip()

    if not secret:

        raise HTTPException(
            status_code=503,
            detail=(
                "Resend webhook verification "
                "is not configured."
            ),
        )

    # IMPORTANT:
    # Keep the original raw request body.
    # The webhook signature must be verified
    # against these exact bytes.
    raw_body = await request.body()

    webhook_id = _required_header(
        request,
        "svix-id",
        "webhook-id",
    )

    webhook_timestamp = (
        _required_header(
            request,
            "svix-timestamp",
            "webhook-timestamp",
        )
    )

    webhook_signature = (
        _required_header(
            request,
            "svix-signature",
            "webhook-signature",
        )
    )

    # -------------------------------------------------
    # 1. Verify signature against RAW body
    # -------------------------------------------------

    try:

        Webhook(
            secret
        ).verify(
            raw_body,
            {
                "svix-id":
                    webhook_id,

                "svix-timestamp":
                    webhook_timestamp,

                "svix-signature":
                    webhook_signature,
            },
        )

    except Exception as error:

        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid webhook signature."
            ),
        ) from error

    # -------------------------------------------------
    # 2. Parse JSON only AFTER verification
    #
    # Newer Svix Python versions no longer return
    # the parsed payload from Webhook.verify().
    # -------------------------------------------------

    try:

        verified_payload = json.loads(
            raw_body.decode(
                "utf-8"
            )
        )

    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:

        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid webhook payload."
            ),
        ) from error

    if not isinstance(
        verified_payload,
        dict,
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid webhook payload."
            ),
        )

    # -------------------------------------------------
    # 3. Process verified provider event
    # -------------------------------------------------

    try:

        result = (
            process_resend_webhook(
                db,
                external_event_id=(
                    webhook_id
                ),
                payload=(
                    verified_payload
                ),
            )
        )

        db.commit()

        return {
            "status":
                "ok",

            "duplicate":
                result.duplicate,

            "correlated":
                result.correlated,

            "eventType":
                result.event_type,

            "invitationId":
                result.invitation_id,

            "deliveryStatus":
                result.delivery_status,
        }

    except Exception:

        db.rollback()

        raise