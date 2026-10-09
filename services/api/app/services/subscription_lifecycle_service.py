import uuid

from datetime import (
    datetime,
    timezone,
)

from sqlalchemy.orm import Session

from services.api.app.models.commerce import (
    TenantSubscription,
)

from services.api.app.services.audit_service import (
    record_audit_event,
)


class SubscriptionLifecycleError(Exception):
    pass


def suspend_subscription(
    db: Session,
    subscription: TenantSubscription,
    reason: str | None = None,
    actor_user_id: uuid.UUID | None = None,
):

    # Preserve idempotency: no transition means no new audit event.
    if subscription.status == "suspended":
        return

    if subscription.status != "active":
        raise SubscriptionLifecycleError(
            f"Cannot suspend subscription "
            f"from status {subscription.status}."
        )

    now = datetime.now(
        timezone.utc
    )

    previous_status = subscription.status

    subscription.status = "suspended"
    subscription.suspended_at = now
    subscription.suspension_reason = reason

    # Audit flush and subscription update share the same transaction.
    # record_audit_event does not commit; this service commits both.
    record_audit_event(
        db,
        action="subscription.suspended",
        resource_type="tenant_subscription",
        resource_id=subscription.id,
        actor_user_id=actor_user_id,
        tenant_id=subscription.tenant_id,
        outcome="success",
        message="Tenant subscription suspended.",
        metadata={
            "previousStatus": previous_status,
            "newStatus": "suspended",
            "offerId": str(subscription.offer_id),
            "suspensionReason": reason,
            "suspendedAt": now.isoformat(),
        },
    )

    db.commit()


def resume_subscription(
    db: Session,
    subscription: TenantSubscription,
    actor_user_id: uuid.UUID | None = None,
):

    # Preserve idempotency: no transition means no new audit event.
    if subscription.status == "active":
        return

    if subscription.status != "suspended":
        raise SubscriptionLifecycleError(
            f"Cannot resume subscription "
            f"from status {subscription.status}."
        )

    now = datetime.now(
        timezone.utc
    )

    if (
        subscription.ends_at
        and subscription.ends_at <= now
    ):
        raise SubscriptionLifecycleError(
            "Subscription has already expired."
        )

    previous_status = subscription.status
    previous_suspension_reason = subscription.suspension_reason

    subscription.status = "active"
    subscription.resumed_at = now
    subscription.suspension_reason = None

    record_audit_event(
        db,
        action="subscription.resumed",
        resource_type="tenant_subscription",
        resource_id=subscription.id,
        actor_user_id=actor_user_id,
        tenant_id=subscription.tenant_id,
        outcome="success",
        message="Tenant subscription resumed.",
        metadata={
            "previousStatus": previous_status,
            "newStatus": "active",
            "offerId": str(subscription.offer_id),
            "previousSuspensionReason": previous_suspension_reason,
            "resumedAt": now.isoformat(),
        },
    )

    db.commit()
