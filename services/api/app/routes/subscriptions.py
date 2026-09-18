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

from services.api.app.schemas.subscription import (
    SubscriptionSuspendRequest,
)

from services.api.app.services.authorization_service import (
    AuthorizationError,
    require_tenant_permission,
)

from services.api.app.services.subscription_lifecycle_service import (
    SubscriptionLifecycleError,
    resume_subscription,
    suspend_subscription,
)

from services.api.app.services.version_policy_service import (
    VersionPolicyError,
    resolve_subscription_baseline,
)


router = APIRouter(
    prefix="/api/v1",
    tags=["Subscriptions"],
)


# =========================================================
# SUBSCRIBE TO OFFER
# =========================================================

@router.post(
    "/tenants/{tenant_id}/offers/{offer_id}/subscribe",
    status_code=201,
)
def subscribe_to_offer(
    tenant_id: uuid.UUID,
    offer_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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

    # -----------------------------------------------------
    # RBAC
    # -----------------------------------------------------

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
        ) from error

    # -----------------------------------------------------
    # Offer
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # Prevent duplicate live subscriptions.
    #
    # Suspended is still an existing subscription and must
    # be resumed rather than creating another subscription.
    # -----------------------------------------------------

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

            TenantSubscription.status.in_(
                (
                    "active",
                    "suspended",
                )
            ),

            ApplicationOffer.application_id
            == application.id,
        )
    )

    if existing:

        raise HTTPException(
            status_code=409,
            detail=(
                "Tenant already has an active or suspended "
                "subscription for this application"
            ),
        )

    # -----------------------------------------------------
    # Load entitlement templates from offer.
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # Resolve commercial version baseline.
    #
    # For same_major:
    # 1.0.0 baseline allows 1.x
    #
    # For pinned:
    # baseline resolves to pinned version.
    # -----------------------------------------------------

    try:

        baseline_version = (
            resolve_subscription_baseline(
                db=db,
                offer=offer,
            )
        )

    except VersionPolicyError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    now = datetime.now(
        timezone.utc
    )

    # -----------------------------------------------------
    # Create commercial subscription snapshot.
    #
    # IMPORTANT:
    # Copy version policy from the offer into the
    # subscription. Future offer changes must not silently
    # change an existing customer's contract.
    # -----------------------------------------------------

    subscription = TenantSubscription(
        tenant_id=tenant.id,
        offer_id=offer.id,
        created_by_user_id=current_user.id,

        status="active",

        baseline_version_id=baseline_version.id,
        version_policy=offer.version_policy,
        pinned_version_id=offer.pinned_version_id,
        auto_upgrade=offer.auto_upgrade,

        starts_at=now,
    )

    db.add(subscription)

    db.flush()

    # -----------------------------------------------------
    # Snapshot offer entitlements onto subscription.
    # -----------------------------------------------------

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

        "baselineVersionId": str(
            subscription.baseline_version_id
        ),

        "versionPolicy":
            subscription.version_policy,

        "pinnedVersionId": (
            str(subscription.pinned_version_id)
            if subscription.pinned_version_id
            else None
        ),

        "autoUpgrade":
            subscription.auto_upgrade,

        "application": {
            "id": str(application.id),
            "name": application.name,
        },
    }


# =========================================================
# LIST TENANT SUBSCRIPTIONS
# =========================================================

@router.get(
    "/tenants/{tenant_id}/subscriptions"
)
def list_subscriptions(
    tenant_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
        ) from error

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

            "status":
                subscription.status,

            "startsAt":
                subscription.starts_at,

            "endsAt":
                subscription.ends_at,

            "cancelledAt":
                subscription.cancelled_at,

            "suspendedAt":
                subscription.suspended_at,

            "resumedAt":
                subscription.resumed_at,

            "suspensionReason":
                subscription.suspension_reason,

            "baselineVersionId": (
                str(subscription.baseline_version_id)
                if subscription.baseline_version_id
                else None
            ),

            "versionPolicy":
                subscription.version_policy,

            "pinnedVersionId": (
                str(subscription.pinned_version_id)
                if subscription.pinned_version_id
                else None
            ),

            "autoUpgrade":
                subscription.auto_upgrade,

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

        for (
            subscription,
            offer,
            application,
        ) in rows
    ]


# =========================================================
# LIST TENANT ENTITLEMENTS
# =========================================================

@router.get(
    "/tenants/{tenant_id}/entitlements"
)
def list_entitlements(
    tenant_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
        ) from error

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
            == tenant.id
        )
        .order_by(
            SubscriptionEntitlement.created_at.desc()
        )
    ).all()

    return [
        {
            "id": str(entitlement.id),

            "code":
                entitlement.code,

            "status":
                entitlement.status,

            "value":
                entitlement.value_json,

            "startsAt":
                entitlement.starts_at,

            "endsAt":
                entitlement.ends_at,

            "subscriptionId": str(
                subscription.id
            ),

            "subscriptionStatus":
                subscription.status,

            "application": {
                "id": str(application.id),
                "name": application.name,
                "appKey": application.app_key,
            },
        }

        for (
            entitlement,
            subscription,
            offer,
            application,
        ) in rows
    ]


# =========================================================
# SUSPEND SUBSCRIPTION
# =========================================================

@router.post(
    "/subscriptions/{subscription_id}/suspend"
)
def suspend_tenant_subscription(
    subscription_id: uuid.UUID,
    payload: SubscriptionSuspendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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

    # -----------------------------------------------------
    # RBAC
    # -----------------------------------------------------

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
        ) from error

    # -----------------------------------------------------
    # Lifecycle transition
    # active -> suspended
    # -----------------------------------------------------

    try:
        suspend_subscription(
            db=db,
            subscription=subscription,
            reason=payload.reason,
        )

    except SubscriptionLifecycleError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error

    return {
        "status": "SUSPENDED",
        "subscriptionId": str(
            subscription.id
        ),
        "suspendedAt": (
            subscription.suspended_at
        ),
        "reason": (
            subscription.suspension_reason
        ),
    }


# =========================================================
# RESUME SUBSCRIPTION
# =========================================================

@router.post(
    "/subscriptions/{subscription_id}/resume"
)
def resume_tenant_subscription(
    subscription_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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

    # -----------------------------------------------------
    # RBAC
    # -----------------------------------------------------

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
        ) from error

    # -----------------------------------------------------
    # Lifecycle transition
    # suspended -> active
    # -----------------------------------------------------

    try:
        resume_subscription(
            db=db,
            subscription=subscription,
        )

    except SubscriptionLifecycleError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error

    return {
        "status": "ACTIVE",
        "subscriptionId": str(
            subscription.id
        ),
        "resumedAt": (
            subscription.resumed_at
        ),
    }


# =========================================================
# CANCEL SUBSCRIPTION
# =========================================================

@router.post(
    "/subscriptions/{subscription_id}/cancel"
)
def cancel_subscription(
    subscription_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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

    # -----------------------------------------------------
    # RBAC
    # -----------------------------------------------------

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
        ) from error

    # -----------------------------------------------------
    # Idempotent cancellation
    # -----------------------------------------------------

    if subscription.status == "cancelled":

        return {
            "status": "CANCELLED",
            "subscriptionId": str(
                subscription.id
            ),
        }

    # Both active and suspended subscriptions may
    # legitimately be cancelled.

    if subscription.status not in {
        "active",
        "suspended",
    }:

        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot cancel subscription "
                f"from status "
                f"{subscription.status}"
            ),
        )

    now = datetime.now(
        timezone.utc
    )

    subscription.status = "cancelled"
    subscription.cancelled_at = now
    subscription.ends_at = now

    # -----------------------------------------------------
    # Revoke all subscription entitlements.
    # -----------------------------------------------------

    entitlements = list(
        db.scalars(
            select(
                SubscriptionEntitlement
            )
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

        "cancelledAt":
            subscription.cancelled_at,
    }