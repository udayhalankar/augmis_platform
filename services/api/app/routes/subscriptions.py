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

from sqlalchemy import (
    func,
    select,
)

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
    ApplicationInstance,
    ApplicationVersion,
    Tenant,
)

from services.api.app.schemas.subscription import (
    SubscriptionChangeOfferRequest,
    SubscriptionSuspendRequest,
)

from services.api.app.services.audit_service import (
    record_audit_event,
)

from services.api.app.services.instance_limit_service import (
    ACTIVE_INSTANCE_STATUSES,
    acquire_instance_limit_lock,
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
    parse_version,
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
# SUBSCRIPTION DETAIL
# =========================================================

@router.get(
    "/subscriptions/{subscription_id}"
)
def get_subscription_detail(
    subscription_id: uuid.UUID,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    ),
):

    # =====================================================
    # 1. SUBSCRIPTION
    # =====================================================

    subscription = db.get(
        TenantSubscription,
        subscription_id,
    )

    if not subscription:

        raise HTTPException(
            status_code=404,
            detail="Subscription not found",
        )

    # =====================================================
    # 2. TENANT AUTHORIZATION
    # =====================================================

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=subscription.tenant_id,
            permission_code="subscription.view",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 3. TENANT
    # =====================================================

    tenant = db.get(
        Tenant,
        subscription.tenant_id,
    )

    if not tenant:

        raise HTTPException(
            status_code=409,
            detail=(
                "Subscription references "
                "a missing tenant."
            ),
        )

    # =====================================================
    # 4. OFFER
    # =====================================================

    offer = db.get(
        ApplicationOffer,
        subscription.offer_id,
    )

    if not offer:

        raise HTTPException(
            status_code=409,
            detail=(
                "Subscription references "
                "a missing offer."
            ),
        )

    # =====================================================
    # 5. APPLICATION
    # =====================================================

    application = db.get(
        Application,
        offer.application_id,
    )

    if not application:

        raise HTTPException(
            status_code=409,
            detail=(
                "Subscription offer references "
                "a missing application."
            ),
        )

    # =====================================================
    # 6. VERSION SNAPSHOT
    # =====================================================

    baseline_version = None

    if subscription.baseline_version_id:

        baseline_version = db.get(
            ApplicationVersion,
            subscription.baseline_version_id,
        )

    pinned_version = None

    if subscription.pinned_version_id:

        pinned_version = db.get(
            ApplicationVersion,
            subscription.pinned_version_id,
        )

    # =====================================================
    # 7. ENTITLEMENT SNAPSHOT
    # =====================================================

    entitlements = list(
        db.scalars(
            select(
                SubscriptionEntitlement
            )
            .where(
                SubscriptionEntitlement.subscription_id
                == subscription.id
            )
            .order_by(
                SubscriptionEntitlement.code
            )
        )
    )

    # =====================================================
    # 8. RESPONSE
    # =====================================================

    return {
        "id":
            str(subscription.id),

        "status":
            subscription.status,

        "tenant": {
            "id":
                str(tenant.id),

            "name":
                tenant.name,

            "slug":
                tenant.slug,

            "status":
                tenant.status,
        },

        "application": {
            "id":
                str(application.id),

            "publisherId":
                str(application.publisher_id),

            "appKey":
                application.app_key,

            "name":
                application.name,

            "status":
                application.status,
        },

        "offer": {
            "id":
                str(offer.id),

            "offerKey":
                offer.offer_key,

            "name":
                offer.name,

            "deliveryType":
                offer.delivery_type,

            "currentStatus":
                offer.status,
        },

        # Important:
        # These fields belong to the SUBSCRIPTION snapshot,
        # not the current mutable offer definition.

        "versionPolicy":
            subscription.version_policy,

        "baselineVersion": (
            {
                "id":
                    str(baseline_version.id),

                "version":
                    baseline_version.version,

                "status":
                    baseline_version.status,
            }

            if baseline_version

            else None
        ),

        "pinnedVersion": (
            {
                "id":
                    str(pinned_version.id),

                "version":
                    pinned_version.version,

                "status":
                    pinned_version.status,
            }

            if pinned_version

            else None
        ),

        "autoUpgrade":
            subscription.auto_upgrade,

        "entitlements": [
            {
                "id":
                    str(entitlement.id),

                "code":
                    entitlement.code,

                "value":
                    entitlement.value_json,

                "status":
                    entitlement.status,

                "startsAt":
                    entitlement.starts_at,

                "endsAt":
                    entitlement.ends_at,
            }

            for entitlement
            in entitlements
        ],

        "lifecycle": {
            "startsAt":
                subscription.starts_at,

            "endsAt":
                subscription.ends_at,

            "suspendedAt":
                subscription.suspended_at,

            "resumedAt":
                subscription.resumed_at,

            "cancelledAt":
                subscription.cancelled_at,

            "suspensionReason":
                subscription.suspension_reason,
        },

        "createdByUserId":
            str(
                subscription.created_by_user_id
            ),

        "createdAt":
            subscription.created_at,

        "updatedAt":
            subscription.updated_at,
    }



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

# =========================================================
# CHANGE SUBSCRIPTION OFFER
# =========================================================

@router.post(
    "/subscriptions/{subscription_id}/change-offer"
)
def change_subscription_offer(
    subscription_id: uuid.UUID,
    payload: SubscriptionChangeOfferRequest,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    ),
):

    # =====================================================
    # 1. LOAD + LOCK SUBSCRIPTION
    # =====================================================

    subscription = db.scalar(
        select(TenantSubscription)
        .where(
            TenantSubscription.id
            == subscription_id
        )
        .with_for_update()
    )

    if not subscription:

        raise HTTPException(
            status_code=404,
            detail="Subscription not found",
        )

    # =====================================================
    # 2. TENANT AUTHORIZATION
    # =====================================================

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

    # =====================================================
    # 3. SUBSCRIPTION STATE
    # =====================================================

    if subscription.status not in {
        "active",
        "suspended",
    }:

        raise HTTPException(
            status_code=409,
            detail=(
                "Only an active or suspended "
                "subscription can change offer."
            ),
        )

    # =====================================================
    # 4. CURRENT OFFER + APPLICATION
    # =====================================================

    current_offer = db.get(
        ApplicationOffer,
        subscription.offer_id,
    )

    if not current_offer:

        raise HTTPException(
            status_code=409,
            detail=(
                "Subscription references "
                "a missing current offer."
            ),
        )

    application = db.get(
        Application,
        current_offer.application_id,
    )

    if not application:

        raise HTTPException(
            status_code=409,
            detail=(
                "Current offer references "
                "a missing application."
            ),
        )

    # =====================================================
    # 5. TARGET OFFER
    # =====================================================

    target_offer = db.get(
        ApplicationOffer,
        payload.offer_id,
    )

    if not target_offer:

        raise HTTPException(
            status_code=404,
            detail="Target offer not found",
        )

    if target_offer.id == current_offer.id:

        raise HTTPException(
            status_code=409,
            detail=(
                "Subscription is already using "
                "this offer."
            ),
        )

    if target_offer.status != "active":

        raise HTTPException(
            status_code=409,
            detail="Target offer is not active",
        )

    if (
        target_offer.application_id
        != application.id
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "Target offer belongs to "
                "another application."
            ),
        )

    # =====================================================
    # 6. TARGET ENTITLEMENT TEMPLATE
    # =====================================================

    target_entitlements = list(
        db.scalars(
            select(OfferEntitlement)
            .where(
                OfferEntitlement.offer_id
                == target_offer.id,

                OfferEntitlement.status
                == "active",
            )
            .order_by(
                OfferEntitlement.code
            )
        )
    )

    if not target_entitlements:

        raise HTTPException(
            status_code=422,
            detail=(
                "Target offer has no "
                "active entitlements."
            ),
        )

    deploy_template = next(
        (
            entitlement
            for entitlement
            in target_entitlements

            if entitlement.code
            == "application.deploy"
        ),
        None,
    )

    if not deploy_template:

        raise HTTPException(
            status_code=422,
            detail=(
                "Target hosted offer does not "
                "contain application.deploy."
            ),
        )

    # =====================================================
    # 7. RESOLVE NEW VERSION SNAPSHOT
    #
    # Pinned:
    #   use target offer's pinned version.
    #
    # same_major / any:
    #   preserve the subscription's current baseline
    #   where possible. Changing commercial plans should
    #   not silently move the customer's major-version
    #   anchor.
    # =====================================================

    try:

        if target_offer.version_policy == "pinned":

            target_baseline = (
                resolve_subscription_baseline(
                    db=db,
                    offer=target_offer,
                )
            )

        else:

            target_baseline = None

            if subscription.baseline_version_id:

                existing_baseline = db.get(
                    ApplicationVersion,
                    subscription.baseline_version_id,
                )

                if (
                    existing_baseline
                    and
                    existing_baseline.application_id
                    == application.id
                    and
                    existing_baseline.status
                    == "image_ready"
                ):

                    target_baseline = (
                        existing_baseline
                    )

            if not target_baseline:

                target_baseline = (
                    resolve_subscription_baseline(
                        db=db,
                        offer=target_offer,
                    )
                )

    except VersionPolicyError as error:

        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    # =====================================================
    # 8. LOCK APPLICATION INSTANCE CAPACITY
    #
    # Synchronizes the plan change with concurrent
    # deployment/restart capacity checks.
    # =====================================================

    acquire_instance_limit_lock(
        db=db,
        tenant_id=subscription.tenant_id,
        application_id=application.id,
    )

    active_instances = list(
        db.scalars(
            select(ApplicationInstance)
            .where(
                ApplicationInstance.tenant_id
                == subscription.tenant_id,

                ApplicationInstance.application_id
                == application.id,

                ApplicationInstance.status.in_(
                    ACTIVE_INSTANCE_STATUSES
                ),
            )
        )
    )

    # =====================================================
    # 9. VALIDATE TARGET INSTANCE LIMIT
    # =====================================================

    deploy_value = (
        deploy_template.value_json
        or {}
    )

    max_instances = deploy_value.get(
        "maxInstances"
    )

    if max_instances is not None:

        if (
            isinstance(max_instances, bool)
            or
            not isinstance(max_instances, int)
            or
            max_instances < 1
        ):

            raise HTTPException(
                status_code=422,
                detail=(
                    "Target offer has an invalid "
                    "maxInstances entitlement."
                ),
            )

        if (
            len(active_instances)
            > max_instances
        ):

            raise HTTPException(
                status_code=409,
                detail=(
                    "Target offer instance limit "
                    "is below current active usage: "
                    f"{len(active_instances)}/"
                    f"{max_instances}."
                ),
            )

    # =====================================================
    # 10. VALIDATE EXISTING RUNTIMES AGAINST
    #     TARGET VERSION POLICY
    #
    # A commercial plan change must not leave an already
    # running instance outside its new policy.
    # =====================================================

    for instance in active_instances:

        active_version = db.get(
            ApplicationVersion,
            instance.active_version_id,
        )

        if not active_version:

            raise HTTPException(
                status_code=409,
                detail=(
                    "An active instance references "
                    "a missing application version."
                ),
            )

        if target_offer.version_policy == "any":

            continue

        if target_offer.version_policy == "pinned":

            if (
                not target_offer.pinned_version_id
                or
                active_version.id
                != target_offer.pinned_version_id
            ):

                raise HTTPException(
                    status_code=409,
                    detail=(
                        "An active instance is not "
                        "running the version required "
                        "by the target pinned offer."
                    ),
                )

            continue

        if target_offer.version_policy == "same_major":

            try:

                baseline_semver = parse_version(
                    target_baseline.version
                )

                active_semver = parse_version(
                    active_version.version
                )

            except VersionPolicyError as error:

                raise HTTPException(
                    status_code=422,
                    detail=str(error),
                ) from error

            if (
                baseline_semver.major
                != active_semver.major
            ):

                raise HTTPException(
                    status_code=409,
                    detail=(
                        "An active instance is outside "
                        "the major-version policy of "
                        "the target offer."
                    ),
                )

            continue

        raise HTTPException(
            status_code=422,
            detail=(
                "Target offer has an unsupported "
                "version policy."
            ),
        )

    # =====================================================
    # 11. LOAD CURRENT ENTITLEMENT SNAPSHOT
    # =====================================================

    current_entitlements = list(
        db.scalars(
            select(SubscriptionEntitlement)
            .where(
                SubscriptionEntitlement.subscription_id
                == subscription.id
            )
        )
    )

    now = datetime.now(
        timezone.utc
    )

    # =====================================================
    # 12. REPLACE ENTITLEMENT SNAPSHOT
    #
    # All validation has completed before mutation.
    # Delete + flush first because of the unique
    # (subscription_id, code) constraint.
    # =====================================================

    for entitlement in current_entitlements:

        db.delete(entitlement)

    db.flush()

    for template in target_entitlements:

        db.add(
            SubscriptionEntitlement(
                subscription_id=subscription.id,
                code=template.code,
                value_json=template.value_json,
                status="active",
                starts_at=now,
            )
        )

    # =====================================================
    # 13. UPDATE COMMERCIAL SNAPSHOT
    # =====================================================

    old_offer_id = subscription.offer_id

    subscription.offer_id = (
        target_offer.id
    )

    subscription.baseline_version_id = (
        target_baseline.id
    )

    subscription.version_policy = (
        target_offer.version_policy
    )

    subscription.pinned_version_id = (
        target_offer.pinned_version_id
    )

    subscription.auto_upgrade = (
        target_offer.auto_upgrade
    )

    # =====================================================
    # 14. AUDIT
    # =====================================================

    record_audit_event(
        db,
        action="subscription.change_offer",
        resource_type="tenant_subscription",
        resource_id=subscription.id,
        actor_user_id=current_user.id,
        tenant_id=subscription.tenant_id,
        outcome="success",
        message=(
            "Subscription offer changed successfully."
        ),
        metadata={
            "applicationId":
                str(application.id),

            "fromOfferId":
                str(old_offer_id),

            "toOfferId":
                str(target_offer.id),

            "toOfferKey":
                target_offer.offer_key,

            "versionPolicy":
                subscription.version_policy,

            "baselineVersionId":
                str(
                    subscription.baseline_version_id
                ),

            "pinnedVersionId": (
                str(
                    subscription.pinned_version_id
                )
                if subscription.pinned_version_id
                else None
            ),

            "autoUpgrade":
                subscription.auto_upgrade,

            "entitlementCodes": [
                template.code
                for template
                in target_entitlements
            ],
        },
    )

    # =====================================================
    # 15. COMMIT ATOMIC CHANGE
    # =====================================================

    db.commit()

    db.refresh(subscription)

    # =====================================================
    # 16. RESPONSE
    # =====================================================

    return {
        "status":
            "CHANGED",

        "subscriptionId":
            str(subscription.id),

        "tenantId":
            str(subscription.tenant_id),

        "applicationId":
            str(application.id),

        "previousOfferId":
            str(old_offer_id),

        "offer": {
            "id":
                str(target_offer.id),

            "offerKey":
                target_offer.offer_key,

            "name":
                target_offer.name,
        },

        "versionPolicy":
            subscription.version_policy,

        "baselineVersionId":
            str(
                subscription.baseline_version_id
            ),

        "pinnedVersionId": (
            str(subscription.pinned_version_id)
            if subscription.pinned_version_id
            else None
        ),

        "autoUpgrade":
            subscription.auto_upgrade,

        "entitlements": [
            {
                "code":
                    template.code,

                "value":
                    template.value_json,
            }

            for template
            in target_entitlements
        ],
    }