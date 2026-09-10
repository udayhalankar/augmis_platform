from datetime import (
    datetime,
    timezone,
)

from sqlalchemy.orm import Session

from services.api.app.models.commerce import (
    TenantSubscription,
)


class SubscriptionLifecycleError(Exception):
    pass


def suspend_subscription(
    db: Session,
    subscription: TenantSubscription,
    reason: str | None = None,
):

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

    subscription.status = "suspended"
    subscription.suspended_at = now
    subscription.suspension_reason = reason

    db.commit()


def resume_subscription(
    db: Session,
    subscription: TenantSubscription,
):

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

    subscription.status = "active"
    subscription.resumed_at = now
    subscription.suspension_reason = None

    db.commit()