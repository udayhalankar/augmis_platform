import uuid
from datetime import (
    datetime,
    timezone,
)

from sqlalchemy import (
    and_,
    or_,
    select,
)

from sqlalchemy.orm import Session

from services.api.app.models.commerce import (
    ApplicationOffer,
    SubscriptionEntitlement,
    TenantSubscription,
)


class EntitlementError(Exception):
    pass


def get_active_entitlement(
    db: Session,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    entitlement_code: str,
) -> SubscriptionEntitlement | None:

    now = datetime.now(
        timezone.utc
    )

    return db.scalar(
        select(
            SubscriptionEntitlement
        )
        .join(
            TenantSubscription,
            TenantSubscription.id
            == SubscriptionEntitlement.subscription_id,
        )
        .join(
            ApplicationOffer,
            ApplicationOffer.id
            == TenantSubscription.offer_id,
        )
        .where(
            TenantSubscription.tenant_id
            == tenant_id,

            TenantSubscription.status
            == "active",

            ApplicationOffer.application_id
            == application_id,

            ApplicationOffer.status
            == "active",

            SubscriptionEntitlement.code
            == entitlement_code,

            SubscriptionEntitlement.status
            == "active",

            TenantSubscription.starts_at
            <= now,

            or_(
                TenantSubscription.ends_at
                .is_(None),

                TenantSubscription.ends_at
                > now,
            ),

            SubscriptionEntitlement.starts_at
            <= now,

            or_(
                SubscriptionEntitlement.ends_at
                .is_(None),

                SubscriptionEntitlement.ends_at
                > now,
            ),
        )
    )


def require_active_entitlement(
    db: Session,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    entitlement_code: str,
) -> SubscriptionEntitlement:

    entitlement = get_active_entitlement(
        db=db,
        tenant_id=tenant_id,
        application_id=application_id,
        entitlement_code=entitlement_code,
    )

    if not entitlement:

        raise EntitlementError(
            "Tenant does not have an active "
            f"{entitlement_code} entitlement "
            "for this application."
        )

    return entitlement