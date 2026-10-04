# services/api/app/services/email_delivery_service.py
from __future__ import annotations

from dataclasses import dataclass

from datetime import (
    datetime,
    timedelta,
    timezone,
)

from services.api.app.services.auth_service import (
    normalize_email,
)

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from services.api.app.models.email_delivery import (
    EmailDeliveryEvent,
)
from services.api.app.models.iam import (
    TenantInvitation,
)
from services.api.app.services.audit_service import (
    record_audit_event,
)


@dataclass(frozen=True)
class ResendWebhookResult:
    duplicate: bool
    correlated: bool
    event_type: str
    invitation_id: str | None
    delivery_status: str | None


DELIVERY_STATUS_BY_EVENT = {
    "email.sent": "submitted",
    "email.delivered": "delivered",
    "email.delivery_delayed": "delayed",
    "email.bounced": "bounced",
    "email.complained": "complained",
    "email.failed": "failed",
    "email.suppressed": "suppressed",
}

TERMINAL_FAILURE_STATUSES = {
    "bounced",
    "complained",
    "failed",
    "suppressed",
}


def _parse_timestamp(
    value: Any,
) -> datetime:
    if isinstance(
        value,
        datetime,
    ):
        return (
            value
            if value.tzinfo
            else value.replace(
                tzinfo=timezone.utc
            )
        )

    clean = str(
        value or ""
    ).strip()

    if clean:
        try:
            parsed = datetime.fromisoformat(
                clean.replace(
                    "Z",
                    "+00:00",
                )
            )
            return (
                parsed
                if parsed.tzinfo
                else parsed.replace(
                    tzinfo=timezone.utc
                )
            )
        except ValueError:
            pass

    return datetime.now(
        timezone.utc
    )


def _clean_text(
    value: Any,
    max_length: int,
) -> str | None:
    clean = str(
        value or ""
    ).strip()

    if not clean:
        return None

    return clean[:max_length]


def _first_recipient(
    data: dict,
) -> str | None:
    to_value = data.get("to")

    if isinstance(
        to_value,
        list,
    ) and to_value:
        return _clean_text(
            to_value[0],
            320,
        )

    if isinstance(
        to_value,
        str,
    ):
        return _clean_text(
            to_value,
            320,
        )

    return None


def _delivery_error(
    event_type: str,
    data: dict,
) -> str | None:
    if event_type == "email.bounced":
        bounce = data.get("bounce")
        if isinstance(
            bounce,
            dict,
        ):
            return _clean_text(
                bounce.get("message")
                or bounce.get("type"),
                1000,
            )

        return "Email bounced."

    if event_type == "email.complained":
        return (
            "Recipient reported the email as spam."
        )

    if event_type == "email.suppressed":
        return (
            "Email suppressed by provider."
        )

    if event_type == "email.failed":
        error = data.get("error")

        if isinstance(
            error,
            dict,
        ):
            detail = (
                error.get("message")
                or error.get("name")
            )
        else:
            detail = (
                error
                or data.get("reason")
            )

        return (
            _clean_text(
                detail,
                1000,
            )
            or "Email delivery failed."
        )

    if event_type == "email.delivery_delayed":
        return (
            "Email delivery is delayed."
        )

    return None


def _find_invitation(
    db: Session,
    *,
    message_id: str | None,
    provider_message_id: str | None,
    recipient: str | None,
    event_at: datetime,
) -> TenantInvitation | None:

    invitation = None

    # -------------------------------------------------
    # 1. Exact RFC Message-ID match
    # -------------------------------------------------

    if message_id:
        invitation = db.scalar(
            select(
                TenantInvitation
            ).where(
                TenantInvitation
                .delivery_message_id
                == message_id
            )
        )

    # -------------------------------------------------
    # 2. Exact provider email-id match
    # -------------------------------------------------

    if (
        invitation is None
        and provider_message_id
    ):
        invitation = db.scalar(
            select(
                TenantInvitation
            ).where(
                TenantInvitation
                .provider_message_id
                == provider_message_id
            )
        )

    if invitation is not None:
        return invitation

    # -------------------------------------------------
    # 3. SMTP bootstrap correlation
    #
    # Resend may replace the Message-ID generated by
    # the SMTP client. For the first provider webhook,
    # correlate ONLY when exactly one submitted
    # invitation exists for the same recipient in a
    # narrow time window.
    # -------------------------------------------------

    if not recipient:
        return None

    normalized_recipient = (
        normalize_email(
            recipient
        )
    )

    window_start = (
        event_at
        - timedelta(
            minutes=10
        )
    )

    window_end = (
        event_at
        + timedelta(
            minutes=2
        )
    )

    candidates = list(
        db.scalars(
            select(
                TenantInvitation
            )
            .where(
                TenantInvitation
                .email_normalized
                == normalized_recipient,

                TenantInvitation
                .delivery_status
                .in_(
                    [
                        "submitted",
                        "sent",
                    ]
                ),

                TenantInvitation
                .last_sent_at
                .is_not(
                    None
                ),

                TenantInvitation
                .last_sent_at
                >= window_start,

                TenantInvitation
                .last_sent_at
                <= window_end,
            )
            .order_by(
                TenantInvitation
                .last_sent_at
                .desc()
            )
        )
    )

    # Security/correctness rule:
    # never guess between multiple possible sends.
    if len(candidates) != 1:
        return None

    return candidates[0]

def _apply_delivery_event(
    invitation: TenantInvitation,
    *,
    event_type: str,
    event_at: datetime,
    provider_message_id: str | None,
    error_message: str | None,
) -> None:

    if provider_message_id:
        invitation.provider_message_id = (
            provider_message_id
        )

    new_status = (
        DELIVERY_STATUS_BY_EVENT.get(
            event_type
        )
    )

    # Opened/clicked and any future events that are
    # not delivery-state events are stored in history
    # but must not overwrite Delivery status.
    if not new_status:
        return

    current_status = str(
        invitation.delivery_status
        or "not_attempted"
    ).lower()

    # Ignore an older provider event arriving late.
    if (
        invitation.last_delivery_event_at
        and event_at
        < invitation.last_delivery_event_at
    ):
        return

    # Do not downgrade Delivered back to transport
    # states because of a late sent/delayed callback.
    if (
        current_status == "delivered"
        and new_status
        in {
            "submitted",
            "delayed",
        }
    ):
        return

    # Once we know about a terminal delivery problem,
    # a weaker submitted/delayed state must not replace it.
    if (
        current_status
        in TERMINAL_FAILURE_STATUSES
        and new_status
        in {
            "submitted",
            "delayed",
        }
    ):
        return

    invitation.delivery_status = (
        new_status
    )

    invitation.last_delivery_event_at = (
        event_at
    )

    if new_status == "delivered":

        invitation.delivered_at = (
            event_at
        )

        invitation.last_delivery_error = (
            None
        )

    elif (
        new_status
        in TERMINAL_FAILURE_STATUSES
    ):

        invitation.last_delivery_error = (
            error_message
            or "Email delivery failed."
        )[:1000]

    elif new_status == "delayed":

        invitation.last_delivery_error = (
            error_message
            or "Email delivery is delayed."
        )

    elif new_status == "submitted":

        invitation.last_delivery_error = (
            None
        )

def process_resend_webhook(
    db: Session,
    *,
    external_event_id: str,
    payload: dict,
) -> ResendWebhookResult:
    event_type = _clean_text(
        payload.get("type"),
        100,
    ) or "unknown"

    data = payload.get("data")

    if not isinstance(
        data,
        dict,
    ):
        data = {}

    message_id = _clean_text(
        data.get("message_id"),
        320,
    )

    provider_message_id = _clean_text(
        data.get("email_id"),
        120,
    )

    recipient = _first_recipient(
        data
    )

    event_at = _parse_timestamp(
        payload.get("created_at")
        or data.get("created_at")
    )

    invitation = _find_invitation(
    db,
    message_id=message_id,
    provider_message_id=(
        provider_message_id
    ),
    recipient=recipient,
    event_at=event_at,
    )

    insert_result = db.execute(
        pg_insert(
            EmailDeliveryEvent
        )
        .values(
            provider="resend",
            external_event_id=(
                external_event_id
            ),
            event_type=event_type,
            invitation_id=(
                invitation.id
                if invitation
                else None
            ),
            tenant_id=(
                invitation.tenant_id
                if invitation
                else None
            ),
            message_id=message_id,
            provider_message_id=(
                provider_message_id
            ),
            recipient=recipient,
            occurred_at=event_at,
        )
        .on_conflict_do_nothing(
            index_elements=[
                "external_event_id"
            ]
        )
        .returning(
            EmailDeliveryEvent.id
        )
    )

    inserted_event_id = (
        insert_result.scalar_one_or_none()
    )

    if inserted_event_id is None:
        return ResendWebhookResult(
            duplicate=True,
            correlated=(
                invitation is not None
            ),
            event_type=event_type,
            invitation_id=(
                str(invitation.id)
                if invitation
                else None
            ),
            delivery_status=(
                invitation.delivery_status
                if invitation
                else None
            ),
        )

    if invitation:
        error_message = (
            _delivery_error(
                event_type,
                data,
            )
        )

        _apply_delivery_event(
            invitation,
            event_type=event_type,
            event_at=event_at,
            provider_message_id=(
                provider_message_id
            ),
            error_message=(
                error_message
            ),
        )

        record_audit_event(
            db,
            action=(
                "tenant.invitation."
                "delivery.webhook"
            ),
            resource_type=(
                "tenant_invitation"
            ),
            resource_id=(
                invitation.id
            ),
            actor_user_id=None,
            tenant_id=(
                invitation.tenant_id
            ),
            outcome="success",
            message=(
                "Tenant invitation delivery "
                "event received from provider."
            ),
            metadata={
                "provider":
                    "resend",
                "eventType":
                    event_type,
                "externalEventId":
                    external_event_id,
                "providerMessageId":
                    provider_message_id,
                "deliveryStatus":
                    invitation.delivery_status,
            },
        )

    db.flush()

    return ResendWebhookResult(
        duplicate=False,
        correlated=(
            invitation is not None
        ),
        event_type=event_type,
        invitation_id=(
            str(invitation.id)
            if invitation
            else None
        ),
        delivery_status=(
            invitation.delivery_status
            if invitation
            else None
        ),
    )
