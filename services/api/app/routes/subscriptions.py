import uuid

import hashlib
import secrets
import threading
import time

from pathlib import Path

from urllib.parse import (
    quote,
)

from datetime import (
    datetime,
    timezone,
)

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)

from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
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
    ApplicationPackage,
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
    is_version_technically_ready,
    parse_version,
    require_subscription_version_allowed,
    resolve_subscription_baseline,
)


router = APIRouter(
    prefix="/api/v1",
    tags=["Subscriptions"],
)

# =========================================================
# STEP 3C-3B — STATIC APPLICATION RUNTIME
# =========================================================

_STATIC_RUNTIME_SESSION_SECONDS = (
    8 * 60 * 60
)

_STATIC_RUNTIME_TICKET_SECONDS = 60

_STATIC_RUNTIME_SESSIONS: dict[
    str,
    dict,
] = {}

_STATIC_RUNTIME_LOCK = (
    threading.Lock()
)


def _static_runtime_hash(
    value: str,
) -> str:

    return hashlib.sha256(
        value.encode(
            "utf-8"
        )
    ).hexdigest()


def _static_runtime_cookie_name(
    runtime_id: str,
) -> str:

    safe = "".join(
        character
        for character in runtime_id
        if (
            character.isalnum()
            or character in "-_"
        )
    )

    return (
        "augmis_static_"
        + safe[:24]
    )


def _cleanup_static_runtime_sessions() -> None:

    now = time.time()

    with _STATIC_RUNTIME_LOCK:

        expired = [
            runtime_id

            for runtime_id, session
            in _STATIC_RUNTIME_SESSIONS.items()

            if float(
                session.get(
                    "expires_at",
                    0,
                )
            )
            <= now
        ]

        for runtime_id in expired:

            _STATIC_RUNTIME_SESSIONS.pop(
                runtime_id,
                None,
            )


def _subscription_time_is_active(
    subscription: TenantSubscription,
) -> bool:

    now = datetime.now(
        timezone.utc
    )

    if (
        subscription.starts_at
        and subscription.starts_at
        > now
    ):
        return False

    if (
        subscription.ends_at
        and subscription.ends_at
        <= now
    ):
        return False

    return True


def _entitlement_time_is_active(
    entitlement: SubscriptionEntitlement,
) -> bool:

    now = datetime.now(
        timezone.utc
    )

    if (
        entitlement.starts_at
        and entitlement.starts_at
        > now
    ):
        return False

    if (
        entitlement.ends_at
        and entitlement.ends_at
        <= now
    ):
        return False

    return True


def _resolve_static_subscription_access(
    *,
    db: Session,
    tenant: Tenant,
    application: Application,
    subscription_id: uuid.UUID | None = None,
):

    query = (
        select(
            TenantSubscription
        )
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
        .order_by(
            TenantSubscription.created_at
            .desc()
        )
    )

    if subscription_id is not None:

        query = query.where(
            TenantSubscription.id
            == subscription_id
        )

    subscription = db.scalar(
        query
    )

    if (
        not subscription
        or not _subscription_time_is_active(
            subscription
        )
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Tenant does not have an active "
                "subscription for this application."
            ),
        )

    entitlement = db.scalar(
        select(
            SubscriptionEntitlement
        )
        .where(
            SubscriptionEntitlement.subscription_id
            == subscription.id,

            SubscriptionEntitlement.code
            == "application.deploy",

            SubscriptionEntitlement.status
            == "active",
        )
        .order_by(
            SubscriptionEntitlement.created_at
            .desc()
        )
    )

    if (
        not entitlement
        or not _entitlement_time_is_active(
            entitlement
        )
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Tenant does not have an active "
                "application.deploy entitlement."
            ),
        )

    if not subscription.baseline_version_id:

        raise HTTPException(
            status_code=409,
            detail=(
                "Subscription has no baseline version."
            ),
        )

    version = db.get(
        ApplicationVersion,
        subscription.baseline_version_id,
    )

    if not version:

        raise HTTPException(
            status_code=409,
            detail=(
                "Subscription baseline version "
                "no longer exists."
            ),
        )

    if (
        version.application_id
        != application.id
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Subscription version belongs "
                "to another application."
            ),
        )

    if str(
        version.build_type or ""
    ).lower() != "static_web":

        raise HTTPException(
            status_code=409,
            detail=(
                "This application is not a "
                "static web application."
            ),
        )

    if not is_version_technically_ready(
    version
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "Static application version "
                "is not runtime-ready."
            ),
        )

    try:

        require_subscription_version_allowed(
            db=db,
            subscription=subscription,
            target_version=version,
        )

    except VersionPolicyError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    package = db.scalar(
        select(
            ApplicationPackage
        )
        .where(
            ApplicationPackage.application_version_id
            == version.id,

            ApplicationPackage.status
            == "validated",
        )
        .order_by(
            ApplicationPackage.created_at
            .desc()
        )
    )

    if not package:

        raise HTTPException(
            status_code=404,
            detail=(
                "Static application package "
                "not found."
            ),
        )

    source_path = Path(
        package.stored_path
    )

    if not source_path.exists():

        raise HTTPException(
            status_code=404,
            detail=(
                "Static application file is "
                "missing from package storage."
            ),
        )

    return (
        subscription,
        entitlement,
        version,
        package,
        source_path,
    )


def _issue_static_runtime_url(
    *,
    request: Request,
    current_user: User,
    tenant: Tenant,
    application: Application,
    subscription: TenantSubscription,
    version: ApplicationVersion,
) -> str:

    _cleanup_static_runtime_sessions()

    runtime_id = (
        secrets.token_urlsafe(
            24
        )
    )

    ticket = (
        secrets.token_urlsafe(
            32
        )
    )

    now = time.time()

    with _STATIC_RUNTIME_LOCK:

        _STATIC_RUNTIME_SESSIONS[
            runtime_id
        ] = {
            "user_id":
                current_user.id,

            "tenant_id":
                tenant.id,

            "application_id":
                application.id,

            "subscription_id":
                subscription.id,

            "version_id":
                version.id,

            "session_hash":
                _static_runtime_hash(
                    ticket
                ),

            "ticket_used":
                False,

            "ticket_expires_at":
                now
                + _STATIC_RUNTIME_TICKET_SECONDS,

            "expires_at":
                now
                + _STATIC_RUNTIME_SESSION_SECONDS,
        }

    base_url = str(
        request.base_url
    ).rstrip("/")

    return (
        f"{base_url}"
        f"/api/v1/static-runtime/"
        f"{runtime_id}/"
        f"?ticket={quote(ticket)}"
    )


def _validate_static_runtime_session(
    *,
    db: Session,
    runtime_id: str,
    cookie_secret: str,
):

    _cleanup_static_runtime_sessions()

    with _STATIC_RUNTIME_LOCK:

        session = (
            _STATIC_RUNTIME_SESSIONS.get(
                runtime_id
            )
        )

        if session:
            session = dict(
                session
            )

    if not session:

        raise HTTPException(
            status_code=401,
            detail=(
                "Static runtime session "
                "is invalid or expired."
            ),
        )

    if (
        not cookie_secret
        or not secrets.compare_digest(
            _static_runtime_hash(
                cookie_secret
            ),
            str(
                session.get(
                    "session_hash",
                    "",
                )
            ),
        )
    ):

        raise HTTPException(
            status_code=401,
            detail=(
                "Static runtime session "
                "cookie is invalid."
            ),
        )

    user = db.get(
        User,
        session["user_id"],
    )

    if not user:

        raise HTTPException(
            status_code=403,
            detail=(
                "Static runtime user "
                "no longer exists."
            ),
        )

    tenant = db.get(
        Tenant,
        session["tenant_id"],
    )

    if not tenant:

        raise HTTPException(
            status_code=404,
            detail="Tenant not found",
        )

    if tenant.status != "active":

        raise HTTPException(
            status_code=403,
            detail="Tenant is not active",
        )

    application = db.get(
        Application,
        session[
            "application_id"
        ],
    )

    if not application:

        raise HTTPException(
            status_code=404,
            detail="Application not found",
        )

    try:

        require_tenant_permission(
            db=db,
            user=user,
            tenant_id=tenant.id,
            permission_code="subscription.view",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    (
        subscription,
        entitlement,
        version,
        package,
        source_path,
    ) = _resolve_static_subscription_access(
        db=db,
        tenant=tenant,
        application=application,
        subscription_id=(
            session[
                "subscription_id"
            ]
        ),
    )

    if version.id != session["version_id"]:

        raise HTTPException(
            status_code=403,
            detail=(
                "Static runtime version "
                "validation failed."
            ),
        )

    return {
        "session":
            session,

        "user":
            user,

        "tenant":
            tenant,

        "application":
            application,

        "subscription":
            subscription,

        "entitlement":
            entitlement,

        "version":
            version,

        "package":
            package,

        "source_path":
            source_path,
    }


@router.post(
    "/tenants/{tenant_id}/applications/{application_id}/open-static"
)
def open_static_application(
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    request: Request,

    db: Session = Depends(
        get_db
    ),

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

    if tenant.status != "active":

        raise HTTPException(
            status_code=403,
            detail="Tenant is not active",
        )

    application = db.get(
        Application,
        application_id,
    )

    if not application:

        raise HTTPException(
            status_code=404,
            detail="Application not found",
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

    (
        subscription,
        _entitlement,
        version,
        _package,
        _source_path,
    ) = _resolve_static_subscription_access(
        db=db,
        tenant=tenant,
        application=application,
    )

    runtime_url = (
        _issue_static_runtime_url(
            request=request,
            current_user=current_user,
            tenant=tenant,
            application=application,
            subscription=subscription,
            version=version,
        )
    )

    return {
        "status":
            "STATIC",

        "tenantId":
            str(tenant.id),

        "applicationId":
            str(application.id),

        "subscriptionId":
            str(subscription.id),

        "versionId":
            str(version.id),

        "version":
            version.version,

        "runtimeUrl":
            runtime_url,
    }


@router.get(
    "/static-runtime/{runtime_id}/",
    response_class=HTMLResponse,
)
def static_runtime(
    runtime_id: str,
    request: Request,

    db: Session = Depends(
        get_db
    ),
):

    cookie_name = (
        _static_runtime_cookie_name(
            runtime_id
        )
    )

    ticket = str(
        request.query_params.get(
            "ticket",
            "",
        )
    ).strip()

    if ticket:

        _cleanup_static_runtime_sessions()

        with _STATIC_RUNTIME_LOCK:

            session = (
                _STATIC_RUNTIME_SESSIONS.get(
                    runtime_id
                )
            )

            now = time.time()

            valid_ticket = (
                bool(session)
                and not bool(
                    session.get(
                        "ticket_used"
                    )
                )
                and float(
                    session.get(
                        "ticket_expires_at",
                        0,
                    )
                )
                > now
                and secrets.compare_digest(
                    _static_runtime_hash(
                        ticket
                    ),
                    str(
                        session.get(
                            "session_hash",
                            "",
                        )
                    ),
                )
            )

            if valid_ticket:

                session[
                    "ticket_used"
                ] = True

        if not valid_ticket:

            raise HTTPException(
                status_code=401,
                detail=(
                    "Static runtime launch "
                    "ticket is invalid or expired."
                ),
            )

        clean_url = (
            f"/api/v1/static-runtime/"
            f"{runtime_id}/"
        )

        response = RedirectResponse(
            url=clean_url,
            status_code=303,
        )

        response.set_cookie(
            key=cookie_name,
            value=ticket,
            max_age=(
                _STATIC_RUNTIME_SESSION_SECONDS
            ),
            httponly=True,
            secure=(
                request.url.scheme
                == "https"
            ),
            samesite="lax",
            path=(
                f"/api/v1/static-runtime/"
                f"{runtime_id}"
            ),
        )

        return response

    cookie_secret = str(
        request.cookies.get(
            cookie_name,
            "",
        )
    ).strip()

    context = (
        _validate_static_runtime_session(
            db=db,
            runtime_id=runtime_id,
            cookie_secret=(
                cookie_secret
            ),
        )
    )

    source_path = context[
        "source_path"
    ]

    try:

        html = source_path.read_text(
            encoding="utf-8"
        )

    except UnicodeDecodeError as error:

        raise HTTPException(
            status_code=422,
            detail=(
                "Stored static application "
                "is not valid UTF-8 HTML."
            ),
        ) from error

    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control":
                "no-store",

            "X-Content-Type-Options":
                "nosniff",

            "Referrer-Policy":
                "no-referrer",

            "Content-Security-Policy": (
                "default-src 'self' data: blob:; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; "
                "font-src 'self' data:; "
                "connect-src 'self'; "
                "object-src 'none'; "
                "base-uri 'none'; "
                "form-action 'self'; "
                "frame-ancestors 'self'"
            ),
        },
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

@router.get(
    "/tenants/{tenant_id}/applications"
)
def list_tenant_available_applications(
    tenant_id: uuid.UUID,

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):
    """
    Tenant-safe application catalog.

    Access is derived from the tenant's ACTIVE commercial
    subscription snapshot and ACTIVE application.deploy
    entitlement.

    IMPORTANT:
    We deliberately do NOT require the current mutable offer
    to still be active and we do NOT require the application
    version to still be commercially published.

    Reason:
    once a tenant has a valid active subscription, later
    publisher retirement prevents NEW sales but should not
    silently remove an existing tenant's contractual access.

    Runtime launch enforcement remains a separate concern.
    """

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

    now = datetime.now(
        timezone.utc
    )

    rows = db.execute(
        select(
            TenantSubscription,
            ApplicationOffer,
            Application,
            SubscriptionEntitlement,
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
        .join(
            SubscriptionEntitlement,
            SubscriptionEntitlement.subscription_id
            == TenantSubscription.id,
        )
        .where(
            TenantSubscription.tenant_id
            == tenant.id,

            TenantSubscription.status
            == "active",

            (
                TenantSubscription.starts_at
                .is_(None)
                |
                (
                    TenantSubscription.starts_at
                    <= now
                )
            ),

            (
                TenantSubscription.ends_at
                .is_(None)
                |
                (
                    TenantSubscription.ends_at
                    > now
                )
            ),

            SubscriptionEntitlement.code
            == "application.deploy",

            SubscriptionEntitlement.status
            == "active",

            (
                SubscriptionEntitlement.starts_at
                .is_(None)
                |
                (
                    SubscriptionEntitlement.starts_at
                    <= now
                )
            ),

            (
                SubscriptionEntitlement.ends_at
                .is_(None)
                |
                (
                    SubscriptionEntitlement.ends_at
                    > now
                )
            ),
        )
        .order_by(
            Application.name.asc()
        )
    ).all()

    items = []

    for (
        subscription,
        offer,
        application,
        deploy_entitlement,
    ) in rows:

        version = None

        if subscription.baseline_version_id:
            version = db.get(
                ApplicationVersion,
                subscription.baseline_version_id,
            )

        if not version:
            continue

        technical_status = str(
            version.status or ""
        ).lower()

        build_type = str(
            version.build_type or ""
        ).lower()

        runtime_ready = (
            technical_status == "validated"
            if build_type == "static_web"
            else technical_status == "image_ready"
        )

        items.append(
            {
                "subscriptionId":
                    str(subscription.id),

                "tenant": {
                    "id":
                        str(tenant.id),

                    "name":
                        tenant.name,

                    "slug":
                        tenant.slug,
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

                    "description":
                        application.description,

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

                "subscription": {
                    "status":
                        subscription.status,

                    "startsAt":
                        subscription.starts_at,

                    "endsAt":
                        subscription.ends_at,

                    "versionPolicy":
                        subscription.version_policy,

                    "autoUpgrade":
                        subscription.auto_upgrade,
                },

                "version": {
                    "id":
                        str(version.id),

                    "version":
                        version.version,

                    "technicalStatus":
                        version.status,

                    "publicationStatus":
                        getattr(
                            version,
                            "publication_status",
                            "draft",
                        ),

                    "buildType":
                        version.build_type,

                    "deploymentMode":
                        version.deployment_mode,
                },

                "entitlement": {
                    "code":
                        deploy_entitlement.code,

                    "status":
                        deploy_entitlement.status,

                    "value":
                        deploy_entitlement.value_json,
                },

                "available":
                    True,

                "runtimeReady":
                    runtime_ready,
            }
        )

    return {
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

        "count":
            len(items),

        "items":
            items,
    }



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
                    is_version_technically_ready(
                        existing_baseline
                    )
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