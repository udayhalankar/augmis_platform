import uuid
from datetime import (
    datetime,
    timezone,
)

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.core.auth import (
    get_current_user,
)

from services.api.app.db.session import (
    get_db,
)

from services.api.app.models.commerce import (
    ApplicationOffer,
    OfferEntitlement,
    SubscriptionEntitlement,
    TenantSubscription,
)

from services.api.app.models.iam import (
    User,
)

from services.api.app.models.platform import (
    Application,
    Tenant,
)

from services.api.app.services.authorization_service import (
    AuthorizationError,
    require_tenant_permission,
)


router = APIRouter(
    prefix="/api/v1",
    tags=["Subscriptions"],
)


@router.post(
    "/tenants/{tenant_id}/offers/{offer_id}/subscribe",
    status_code=201,
)
def subscribe_to_offer(
    tenant_id: uuid.UUID,
    offer_id: uuid.UUID,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    ),
):

    tenant = db.get(
        Tenant,
        tenant_id,
    )

    if not tenant:

        raise HTTPException(
            status_code=404,
            detail="Tenant not found",
        )

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=tenant.id,
            permission_code="subscription.manage",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        )

    offer = db.get(
        ApplicationOffer,
        offer_id,
    )

    if not offer:

        raise HTTPException(
            status_code=404,
            detail="Offer not found",
        )

    if offer.status != "active":

        raise HTTPException(
            status_code=409,
            detail="Offer is not active",
        )

    application = db.get(
        Application,
        offer.application_id,
    )

    if not application:

        raise HTTPException(
            status_code=404,
            detail="Application not found",
        )

    existing = db.scalar(
        select(TenantSubscription)
        .join(
            ApplicationOffer,
            ApplicationOffer.id
            == TenantSubscription.offer_id,
        )
        .where(
            TenantSubscription.tenant_id
            == tenant.id,

            TenantSubscription.status
            == "active",

            ApplicationOffer.application_id
            == application.id,
        )
    )

    if existing:

        raise HTTPException(
            status_code=409,
            detail=(
                "Tenant already has an active "
                "subscription for this application"
            ),
        )

    offer_entitlements = list(
        db.scalars(
            select(OfferEntitlement)
            .where(
                OfferEntitlement.offer_id
                == offer.id,

                OfferEntitlement.status
                == "active",
            )
        )
    )

    if not offer_entitlements:

        raise HTTPException(
            status_code=422,
            detail="Offer has no active entitlements",
        )

    now = datetime.now(
        timezone.utc
    )

    subscription = TenantSubscription(
        tenant_id=tenant.id,
        offer_id=offer.id,
        created_by_user_id=current_user.id,
        status="active",
        starts_at=now,
    )

    db.add(subscription)

    db.flush()

    for template in offer_entitlements:

        db.add(
            SubscriptionEntitlement(
                subscription_id=subscription.id,
                code=template.code,
                value_json=template.value_json,
                status="active",
                starts_at=now,
            )
        )

    db.commit()

    db.refresh(subscription)

    return {
        "status": "ACTIVE",
        "subscriptionId": str(
            subscription.id
        ),
        "tenantId": str(
            subscription.tenant_id
        ),
        "offerId": str(
            subscription.offer_id
        ),
        "application": {
            "id": str(application.id),
            "name": application.name,
        },
    }


@router.get(
    "/tenants/{tenant_id}/subscriptions"
)
def list_subscriptions(
    tenant_id: uuid.UUID,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    ),
):

    tenant = db.get(
        Tenant,
        tenant_id,
    )

    if not tenant:

        raise HTTPException(
            status_code=404,
            detail="Tenant not found",
        )

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=tenant.id,
            permission_code="subscription.view",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        )

    rows = db.execute(
        select(
            TenantSubscription,
            ApplicationOffer,
            Application,
        )
        .join(
            ApplicationOffer,
            ApplicationOffer.id
            == TenantSubscription.offer_id,
        )
        .join(
            Application,
            Application.id
            == ApplicationOffer.application_id,
        )
        .where(
            TenantSubscription.tenant_id
            == tenant.id
        )
        .order_by(
            TenantSubscription.created_at.desc()
        )
    ).all()

    return [
        {
            "id": str(subscription.id),
            "status": subscription.status,
            "startsAt": subscription.starts_at,
            "endsAt": subscription.ends_at,
            "offer": {
                "id": str(offer.id),
                "name": offer.name,
                "offerKey": offer.offer_key,
            },
            "application": {
                "id": str(application.id),
                "name": application.name,
                "appKey": application.app_key,
            },
        }

        for subscription, offer, application
        in rows
    ]


@router.get(
    "/tenants/{tenant_id}/entitlements"
)
def list_entitlements(
    tenant_id: uuid.UUID,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    ),
):

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=tenant_id,
            permission_code="subscription.view",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        )

    rows = db.execute(
        select(
            SubscriptionEntitlement,
            TenantSubscription,
            ApplicationOffer,
            Application,
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
        .join(
            Application,
            Application.id
            == ApplicationOffer.application_id,
        )
        .where(
            TenantSubscription.tenant_id
            == tenant_id
        )
        .order_by(
            SubscriptionEntitlement.created_at.desc()
        )
    ).all()

    return [
        {
            "id": str(entitlement.id),
            "code": entitlement.code,
            "status": entitlement.status,
            "value": entitlement.value_json,
            "application": {
                "id": str(application.id),
                "name": application.name,
            },
            "subscriptionId": str(
                subscription.id
            ),
        }

        for (
            entitlement,
            subscription,
            offer,
            application,
        ) in rows
    ]


@router.post(
    "/subscriptions/{subscription_id}/cancel"
)
def cancel_subscription(
    subscription_id: uuid.UUID,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    ),
):

    subscription = db.get(
        TenantSubscription,
        subscription_id,
    )

    if not subscription:

        raise HTTPException(
            status_code=404,
            detail="Subscription not found",
        )

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=subscription.tenant_id,
            permission_code="subscription.manage",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        )

    if subscription.status == "cancelled":

        return {
            "status": "CANCELLED",
            "subscriptionId": str(
                subscription.id
            ),
        }

    if subscription.status != "active":

        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot cancel subscription "
                f"from status {subscription.status}"
            ),
        )

    now = datetime.now(
        timezone.utc
    )

    subscription.status = "cancelled"
    subscription.cancelled_at = now
    subscription.ends_at = now

    entitlements = list(
        db.scalars(
            select(SubscriptionEntitlement)
            .where(
                SubscriptionEntitlement.subscription_id
                == subscription.id
            )
        )
    )

    for entitlement in entitlements:

        entitlement.status = "revoked"
        entitlement.ends_at = now

    db.commit()

    return {
        "status": "CANCELLED",
        "subscriptionId": str(
            subscription.id
        ),
    }