# services/api/app/routes/offers.py
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
)

from services.api.app.models.iam import (
    User,
)

from services.api.app.models.platform import (
    Application,
    ApplicationVersion,
)

from services.api.app.schemas.offer import (
    OfferCreate,
    OfferUpdate,
)

from services.api.app.services.authorization_service import (
    AuthorizationError,
    require_publisher_permission,
)

from services.api.app.services.audit_service import (
    record_audit_event,
)

from services.api.app.services.version_policy_service import (
    VersionPolicyError,
    validate_offer_version_policy,
)


router = APIRouter(
    prefix="/api/v1",
    tags=["Offers"],
)


# =========================================================
# HELPER - SERIALIZE OFFER
# =========================================================

def serialize_offer(
    db: Session,
    offer: ApplicationOffer,
) -> dict:

    entitlements = list(
        db.scalars(
            select(
                OfferEntitlement
            )
            .where(
                OfferEntitlement.offer_id
                == offer.id
            )
            .order_by(
                OfferEntitlement.code
            )
        )
    )

    return {
        "id":
            str(offer.id),

        "applicationId":
            str(
                offer.application_id
            ),

        "offerKey":
            offer.offer_key,

        "name":
            offer.name,

        "description":
            offer.description,

        "deliveryType":
            offer.delivery_type,

        "status":
            offer.status,

        "versionPolicy":
            offer.version_policy,

        "pinnedVersionId": (
            str(
                offer.pinned_version_id
            )
            if offer.pinned_version_id
            else None
        ),

        "autoUpgrade":
            offer.auto_upgrade,

        "entitlements": [
            {
                "id":
                    str(
                        entitlement.id
                    ),

                "code":
                    entitlement.code,

                "value":
                    entitlement.value_json,

                "status":
                    entitlement.status,
            }

            for entitlement
            in entitlements
        ],

        "activatedAt":
            offer.activated_at,

        "createdAt":
            offer.created_at,

        "updatedAt":
            offer.updated_at,
    }


@router.get(
    "/marketplace/offers"
)
def list_marketplace_offers(
    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    ),
):
    """
    Authenticated marketplace catalog.

    Only exposes:
    - active offers
    - whose application is published
    - with a published application version

    It does NOT grant a tenant subscription.
    Subscription is Step 3B.
    """

    offers = list(
        db.scalars(
            select(
                ApplicationOffer
            )
            .where(
                ApplicationOffer.status
                == "active"
            )
            .order_by(
                ApplicationOffer.created_at
                .desc()
            )
        )
    )

    result = []

    for offer in offers:

        application = db.get(
            Application,
            offer.application_id
        )

        if not application:
            continue

        if str(
            application.status or ""
        ).lower() != "published":
            continue



        # ==============================================
        # RESOLVE THE MARKETPLACE VERSION
        # ==============================================

        version = None

        if offer.version_policy == "pinned":

            if not offer.pinned_version_id:
                continue

            candidate = db.get(
                ApplicationVersion,
                offer.pinned_version_id
            )

            if (
                candidate
                and
                candidate.application_id
                    == application.id
                and
                str(
                    candidate.publication_status or ""
                ).lower()
                    == "published"
            ):
                version = candidate

        else:

            version = db.scalar(
                select(
                    ApplicationVersion
                )
                .where(
                    ApplicationVersion.application_id
                        == application.id,

                    ApplicationVersion.publication_status
                        == "published",
                )
                .order_by(
                    ApplicationVersion.created_at
                        .desc()
                )
            )

        if not version:
            continue


        entitlements = list(
            db.scalars(
                select(
                    OfferEntitlement
                )
                .where(
                    OfferEntitlement.offer_id
                        == offer.id,

                    OfferEntitlement.status
                        == "active",
                )
                .order_by(
                    OfferEntitlement.code
                )
            )
        )


        result.append(
            {
                "id":
                    str(offer.id),

                "offerKey":
                    offer.offer_key,

                "name":
                    offer.name,

                "description":
                    offer.description,

                "deliveryType":
                    offer.delivery_type,

                "status":
                    offer.status,

                "versionPolicy":
                    offer.version_policy,

                "autoUpgrade":
                    offer.auto_upgrade,

                "application": {
                    "id":
                        str(application.id),

                    "appKey":
                        application.app_key,

                    "name":
                        application.name,

                    "description":
                        application.description,

                    "status":
                        application.status,
                },

                "version": {
                    "id":
                        str(version.id),

                    "version":
                        version.version,

                    "buildType":
                        version.build_type,

                    "deploymentMode":
                        version.deployment_mode,

                    "status":
                        version.status,

                    "publicationStatus":
                        version.publication_status,
                },

                "entitlements": [
                    {
                        "code":
                            entitlement.code,

                        "value":
                            entitlement.value_json,
                    }

                    for entitlement
                    in entitlements
                ],
            }
        )

    return result

# =========================================================
# LIST APPLICATION OFFERS
# =========================================================

@router.get(
    "/applications/{application_id}/offers"
)
def list_application_offers(
    application_id: uuid.UUID,

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    # =====================================================
    # 1. APPLICATION
    # =====================================================

    application = db.get(
        Application,
        application_id,
    )

    if not application:

        raise HTTPException(
            status_code=404,
            detail="Application not found",
        )

    # =====================================================
    # 2. AUTHORIZATION
    # =====================================================

    try:

        require_publisher_permission(
            db=db,
            user=current_user,

            publisher_id=(
                application.publisher_id
            ),

            permission_code="offer.manage",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 3. OFFERS
    # =====================================================

    offers = list(
        db.scalars(
            select(
                ApplicationOffer
            )
            .where(
                ApplicationOffer.application_id
                == application.id
            )
            .order_by(
                ApplicationOffer.created_at.desc()
            )
        )
    )

    # =====================================================
    # 4. RESPONSE
    # =====================================================

    return [
        serialize_offer(
            db,
            offer,
        )

        for offer
        in offers
    ]


# =========================================================
# CREATE OFFER
# =========================================================

@router.post(
    "/applications/{application_id}/offers",
    status_code=201,
)
def create_offer(
    application_id: uuid.UUID,

    payload: OfferCreate,

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    # =====================================================
    # 1. APPLICATION
    # =====================================================

    application = db.get(
        Application,
        application_id,
    )

    if not application:

        raise HTTPException(
            status_code=404,
            detail="Application not found",
        )

    # =====================================================
    # 2. AUTHORIZATION
    # =====================================================

    try:

        require_publisher_permission(
            db=db,
            user=current_user,
            publisher_id=(
                application.publisher_id
            ),
            permission_code="offer.manage",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 3. DUPLICATE KEY
    # =====================================================

    existing = db.scalar(
        select(
            ApplicationOffer
        )
        .where(
            ApplicationOffer.application_id
            == application.id,

            ApplicationOffer.offer_key
            == payload.offer_key,
        )
    )

    if existing:

        raise HTTPException(
            status_code=409,
            detail=(
                "Offer key already exists "
                "for this application"
            ),
        )

    # =====================================================
    # 4. DELIVERY TYPE
    # =====================================================

    if (
        payload.delivery_type
        != "hosted_dedicated"
    ):

        raise HTTPException(
            status_code=422,
            detail=(
                "Only hosted_dedicated "
                "is currently supported"
            ),
        )

    # =====================================================
    # 5. ENTITLEMENTS
    # =====================================================

    if not payload.entitlements:

        raise HTTPException(
            status_code=422,
            detail=(
                "Offer must define at least "
                "one entitlement"
            ),
        )

    entitlement_codes = [
        item.code
        for item
        in payload.entitlements
    ]

    if (
        len(entitlement_codes)
        != len(
            set(
                entitlement_codes
            )
        )
    ):

        raise HTTPException(
            status_code=422,
            detail=(
                "Duplicate entitlement "
                "codes are not allowed."
            ),
        )

    if (
        "application.deploy"
        not in entitlement_codes
    ):

        raise HTTPException(
            status_code=422,
            detail=(
                "Hosted offer must include "
                "application.deploy entitlement"
            ),
        )

    # =====================================================
    # 6. VERSION POLICY
    # =====================================================

    try:

        validate_offer_version_policy(
            db=db,

            offer_application_id=(
                application.id
            ),

            version_policy=(
                payload.version_policy
            ),

            pinned_version_id=(
                payload.pinned_version_id
            ),
        )

    except VersionPolicyError as error:

        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    # =====================================================
    # 7. CREATE OFFER
    # =====================================================

    offer = ApplicationOffer(
        application_id=(
            application.id
        ),

        offer_key=(
            payload.offer_key
        ),

        name=(
            payload.name
        ),

        description=(
            payload.description
        ),

        delivery_type=(
            payload.delivery_type
        ),

        status="draft",

        version_policy=(
            payload.version_policy
        ),

        pinned_version_id=(
            payload.pinned_version_id
        ),

        auto_upgrade=(
            payload.auto_upgrade
        ),
    )

    db.add(
        offer
    )

    db.flush()

    # =====================================================
    # 8. CREATE ENTITLEMENTS
    # =====================================================

    for item in (
        payload.entitlements
    ):

        db.add(
            OfferEntitlement(
                offer_id=offer.id,

                code=item.code,

                value_json=(
                    item.value
                ),

                status="active",
            )
        )

    # =====================================================
    # 9. AUDIT + COMMIT
    # =====================================================

    record_audit_event(
        db,
        action="offer.created",
        resource_type="application_offer",
        resource_id=offer.id,
        actor_user_id=current_user.id,
        publisher_id=application.publisher_id,
        outcome="success",
        message="Application offer created.",
        metadata={
            "applicationId": str(application.id),
            "offerKey": offer.offer_key,
            "status": offer.status,
            "deliveryType": offer.delivery_type,
            "versionPolicy": offer.version_policy,
            "pinnedVersionId": (
                str(offer.pinned_version_id)
                if offer.pinned_version_id
                else None
            ),
            "autoUpgrade": offer.auto_upgrade,
            "entitlementCodes": entitlement_codes,
        },
    )

    db.commit()

    db.refresh(
        offer
    )

    return serialize_offer(
        db,
        offer,
    )


# =========================================================
# UPDATE DRAFT OFFER
# =========================================================

@router.patch(
    "/offers/{offer_id}"
)
def update_offer(
    offer_id: uuid.UUID,

    payload: OfferUpdate,

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    # =====================================================
    # 1. OFFER
    # =====================================================

    offer = db.get(
        ApplicationOffer,
        offer_id,
    )

    if not offer:

        raise HTTPException(
            status_code=404,
            detail="Offer not found",
        )

    # =====================================================
    # 2. APPLICATION
    # =====================================================

    application = db.get(
        Application,
        offer.application_id,
    )

    if not application:

        raise HTTPException(
            status_code=409,
            detail=(
                "Offer references a "
                "missing application."
            ),
        )

    # =====================================================
    # 3. AUTHORIZATION
    # =====================================================

    try:

        require_publisher_permission(
            db=db,
            user=current_user,

            publisher_id=(
                application.publisher_id
            ),

            permission_code="offer.manage",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 4. DRAFT ONLY
    # =====================================================

    if (
        offer.status
        != "draft"
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "Only draft offers "
                "can be edited."
            ),
        )

    

    fields_set = (
        payload.model_fields_set
    )

    if not fields_set:

        raise HTTPException(
            status_code=422,
            detail=(
                "No offer fields "
                "were supplied."
            ),
        )

    # =====================================================
    # 5. BASIC FIELDS
    # =====================================================

    if (
        "name"
        in fields_set
    ):

        if (
            payload.name
            is None
        ):

            raise HTTPException(
                status_code=422,
                detail=(
                    "Offer name "
                    "cannot be null."
                ),
            )

        offer.name = (
            payload.name
        )

    if (
        "description"
        in fields_set
    ):

        offer.description = (
            payload.description
        )

    # =====================================================
    # 6. VERSION POLICY
    # =====================================================

    new_version_policy = (
        offer.version_policy
    )

    new_pinned_version_id = (
        offer.pinned_version_id
    )

    if (
        "version_policy"
        in fields_set
    ):

        if (
            payload.version_policy
            is None
        ):

            raise HTTPException(
                status_code=422,
                detail=(
                    "version_policy "
                    "cannot be null."
                ),
            )

        new_version_policy = (
            payload.version_policy
        )

        if (
            new_version_policy
            != "pinned"
            and
            "pinned_version_id"
            not in fields_set
        ):

            new_pinned_version_id = (
                None
            )

    if (
        "pinned_version_id"
        in fields_set
    ):

        new_pinned_version_id = (
            payload.pinned_version_id
        )

    try:

        validate_offer_version_policy(
            db=db,

            offer_application_id=(
                application.id
            ),

            version_policy=(
                new_version_policy
            ),

            pinned_version_id=(
                new_pinned_version_id
            ),
        )

    except VersionPolicyError as error:

        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    offer.version_policy = (
        new_version_policy
    )

    offer.pinned_version_id = (
        new_pinned_version_id
    )

    # =====================================================
    # 7. AUTO UPGRADE
    # =====================================================

    if (
        "auto_upgrade"
        in fields_set
    ):

        if (
            payload.auto_upgrade
            is None
        ):

            raise HTTPException(
                status_code=422,
                detail=(
                    "auto_upgrade "
                    "cannot be null."
                ),
            )

        offer.auto_upgrade = (
            payload.auto_upgrade
        )

    # =====================================================
    # 8. ENTITLEMENTS
    # =====================================================

    if (
        "entitlements"
        in fields_set
    ):

        if not (
            payload.entitlements
        ):

            raise HTTPException(
                status_code=422,
                detail=(
                    "Offer must define "
                    "at least one entitlement."
                ),
            )

        entitlement_codes = [
            item.code

            for item
            in payload.entitlements
        ]

        if (
            len(
                entitlement_codes
            )
            !=
            len(
                set(
                    entitlement_codes
                )
            )
        ):

            raise HTTPException(
                status_code=422,
                detail=(
                    "Duplicate entitlement "
                    "codes are not allowed."
                ),
            )

        if (
            "application.deploy"
            not in entitlement_codes
        ):

            raise HTTPException(
                status_code=422,
                detail=(
                    "Hosted offer must include "
                    "application.deploy entitlement."
                ),
            )

        existing_entitlements = list(
            db.scalars(
                select(
                    OfferEntitlement
                )
                .where(
                    OfferEntitlement.offer_id
                    == offer.id
                )
            )
        )

        for entitlement in (
            existing_entitlements
        ):

            db.delete(
                entitlement
            )

        # Required because
        # (offer_id, code) is unique.
        db.flush()

        for item in (
            payload.entitlements
        ):

            db.add(
                OfferEntitlement(
                    offer_id=(
                        offer.id
                    ),

                    code=(
                        item.code
                    ),

                    value_json=(
                        item.value
                    ),

                    status="active",
                )
            )

    # =====================================================
    # 9. AUDIT + COMMIT
    # =====================================================

    record_audit_event(
        db,
        action="offer.updated",
        resource_type="application_offer",
        resource_id=offer.id,
        actor_user_id=current_user.id,
        publisher_id=application.publisher_id,
        outcome="success",
        message="Draft application offer updated.",
        metadata={
            "applicationId": str(application.id),
            "offerKey": offer.offer_key,
            "changedFields": sorted(fields_set),
            "status": offer.status,
            "versionPolicy": offer.version_policy,
            "pinnedVersionId": (
                str(offer.pinned_version_id)
                if offer.pinned_version_id
                else None
            ),
            "autoUpgrade": offer.auto_upgrade,
        },
    )

    db.commit()

    db.refresh(
        offer
    )

    return serialize_offer(
        db,
        offer,
    )


# =========================================================
# ACTIVATE OFFER
# =========================================================

@router.post(
    "/offers/{offer_id}/activate"
)
def activate_offer(
    offer_id: uuid.UUID,

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    # =====================================================
    # 1. OFFER
    # =====================================================

    offer = db.get(
        ApplicationOffer,
        offer_id,
    )

    if not offer:

        raise HTTPException(
            status_code=404,
            detail="Offer not found",
        )

    # =====================================================
    # 2. APPLICATION
    # =====================================================

    application = db.get(
        Application,
        offer.application_id,
    )

    if not application:

        raise HTTPException(
            status_code=409,
            detail=(
                "Offer references a "
                "missing application."
            ),
        )

    # =====================================================
    # 3. AUTHORIZATION
    # =====================================================

    try:

        require_publisher_permission(
            db=db,
            user=current_user,

            publisher_id=(
                application.publisher_id
            ),

            permission_code="offer.manage",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 4. IDEMPOTENT ACTIVE
    # =====================================================

    if (
        offer.status
        == "active"
    ):

        return {
            "status":
                "ACTIVE",

            "offerId":
                str(
                    offer.id
                ),
        }

    if (
        offer.status
        != "draft"
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "Offer cannot be activated "
                f"from status {offer.status}"
            ),
        )

    # =====================================================
    # 5. APPLICATION MUST BE PUBLISHED
    # =====================================================

    if str(
        application.status or ""
    ).lower() != "published":

        raise HTTPException(
            status_code=409,
            detail=(
                "The application must be published "
                "before its commercial offer can be activated."
            ),
        )


    published_version = None

    if offer.version_policy == "pinned":

        if offer.pinned_version_id:
            candidate = db.get(
                ApplicationVersion,
                offer.pinned_version_id
            )

            if (
                candidate
                and
                candidate.application_id
                    == application.id
                and
                str(
                    candidate.publication_status or ""
                ).lower()
                    == "published"
            ):
                published_version = candidate

    else:

        published_version = db.scalar(
            select(
                ApplicationVersion
            )
            .where(
                ApplicationVersion.application_id
                    == application.id,

                ApplicationVersion.publication_status
                    == "published",
            )
            .order_by(
                ApplicationVersion.created_at.desc()
            )
        )


    if not published_version:

        detail = (
            "The pinned application version must be published "
            "before this offer can be activated."
            if offer.version_policy == "pinned"
            else (
                "The application has no published version. "
                "Publish a version before activating the offer."
            )
        )

        raise HTTPException(
            status_code=409,
            detail=detail,
        )

    # =====================================================
    # 5. ACTIVATE
    # =====================================================

    offer.status = (
        "active"
    )

    offer.activated_at = (
        datetime.now(
            timezone.utc
        )
    )

    record_audit_event(
        db,
        action="offer.activated",
        resource_type="application_offer",
        resource_id=offer.id,
        actor_user_id=current_user.id,
        publisher_id=application.publisher_id,
        outcome="success",
        message="Application offer activated.",
        metadata={
            "applicationId": str(application.id),
            "offerKey": offer.offer_key,
            "versionPolicy": offer.version_policy,
            "publishedVersionId": str(published_version.id),
        },
    )

    db.commit()

    return {
        "status":
            "ACTIVE",

        "offerId":
            str(
                offer.id
            ),
    }


# =========================================================
# RETIRE OFFER
# =========================================================

@router.post(
    "/offers/{offer_id}/retire"
)
def retire_offer(
    offer_id: uuid.UUID,

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    # =====================================================
    # 1. OFFER
    # =====================================================

    offer = db.get(
        ApplicationOffer,
        offer_id,
    )

    if not offer:

        raise HTTPException(
            status_code=404,
            detail="Offer not found",
        )

    # =====================================================
    # 2. APPLICATION
    # =====================================================

    application = db.get(
        Application,
        offer.application_id,
    )

    if not application:

        raise HTTPException(
            status_code=409,
            detail=(
                "Offer references a "
                "missing application."
            ),
        )

    # =====================================================
    # 3. AUTHORIZATION
    # =====================================================

    try:

        require_publisher_permission(
            db=db,
            user=current_user,

            publisher_id=(
                application.publisher_id
            ),

            permission_code="offer.manage",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 4. IDEMPOTENT RETIRED
    # =====================================================

    if (
        offer.status
        == "retired"
    ):

        return {
            "status":
                "RETIRED",

            "offerId":
                str(
                    offer.id
                ),
        }

    if (
        offer.status
        != "active"
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "Offer cannot be retired "
                f"from status {offer.status}"
            ),
        )

    # =====================================================
    # 5. RETIRE
    # =====================================================

    offer.status = (
        "retired"
    )

    record_audit_event(
        db,
        action="offer.retired",
        resource_type="application_offer",
        resource_id=offer.id,
        actor_user_id=current_user.id,
        publisher_id=application.publisher_id,
        outcome="success",
        message="Application offer retired.",
        metadata={
            "applicationId": str(application.id),
            "offerKey": offer.offer_key,
            "status": offer.status,
        },
    )

    db.commit()

    db.refresh(
        offer
    )

    return {
        "status":
            "RETIRED",

        "offerId":
            str(
                offer.id
            ),

        "applicationId":
            str(
                offer.application_id
            ),

        "offerKey":
            offer.offer_key,

        "updatedAt":
            offer.updated_at,
    }