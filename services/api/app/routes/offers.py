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
)

from services.api.app.schemas.offer import (
    OfferCreate,
    OfferUpdate,
)

from services.api.app.services.version_policy_service import (
    VersionPolicyError,
    validate_offer_version_policy,
)

from services.api.app.services.authorization_service import (
    AuthorizationError,
    require_publisher_permission,
)


router = APIRouter(
    prefix="/api/v1",
    tags=["Offers"],
)


@router.post(
    "/applications/{application_id}/offers",
    status_code=201,
)
def create_offer(
    application_id: uuid.UUID,
    payload: OfferCreate,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    ),
):

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

        require_publisher_permission(
            db=db,
            user=current_user,
            publisher_id=application.publisher_id,
            permission_code="offer.manage",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        )

    existing = db.scalar(
        select(ApplicationOffer)
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
            detail="Offer key already exists for this application",
        )

    if payload.delivery_type != "hosted_dedicated":

        raise HTTPException(
            status_code=422,
            detail=(
                "Only hosted_dedicated is currently supported"
            ),
        )

    if not payload.entitlements:

        raise HTTPException(
            status_code=422,
            detail="Offer must define at least one entitlement",
        )

    entitlement_codes = {
        item.code
        for item in payload.entitlements
    }

    if "application.deploy" not in entitlement_codes:

        raise HTTPException(
            status_code=422,
            detail=(
                "Hosted offer must include "
                "application.deploy entitlement"
            ),
        )

    offer = ApplicationOffer(
        application_id=application.id,
        offer_key=payload.offer_key,
        name=payload.name,
        description=payload.description,
        delivery_type=payload.delivery_type,
        status="draft",
    )

    db.add(offer)

    db.flush()

    for item in payload.entitlements:

        db.add(
            OfferEntitlement(
                offer_id=offer.id,
                code=item.code,
                value_json=item.value,
                status="active",
            )
        )

    db.commit()

    db.refresh(offer)

    return {
        "id": str(offer.id),
        "applicationId": str(
            offer.application_id
        ),
        "offerKey": offer.offer_key,
        "name": offer.name,
        "deliveryType": offer.delivery_type,
        "status": offer.status,
    }


@router.post(
    "/offers/{offer_id}/activate"
)
def activate_offer(
    offer_id: uuid.UUID,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    ),
):

    offer = db.get(
        ApplicationOffer,
        offer_id,
    )

    if not offer:

        raise HTTPException(
            status_code=404,
            detail="Offer not found",
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

    try:

        require_publisher_permission(
            db=db,
            user=current_user,
            publisher_id=application.publisher_id,
            permission_code="offer.manage",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        )

    if offer.status == "active":

        return {
            "status": "ACTIVE",
            "offerId": str(offer.id),
        }

    if offer.status != "draft":

        raise HTTPException(
            status_code=409,
            detail=(
                f"Offer cannot be activated "
                f"from status {offer.status}"
            ),
        )

    offer.status = "active"

    offer.activated_at = datetime.now(
        timezone.utc
    )

    db.commit()

    return {
        "status": "ACTIVE",
        "offerId": str(offer.id),
    }


@router.get(
    "/applications/{application_id}/offers"
)
def list_application_offers(
    application_id: uuid.UUID,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    ),
):

    application = db.get(
        Application,
        application_id,
    )

    if not application:

        raise HTTPException(
            status_code=404,
            detail="Application not found",
        )

    offers = list(
        db.scalars(
            select(ApplicationOffer)
            .where(
                ApplicationOffer.application_id
                == application.id
            )
            .order_by(
                ApplicationOffer.created_at.desc()
            )
        )
    )

    return [
        {
            "id": str(offer.id),
            "offerKey": offer.offer_key,
            "name": offer.name,
            "deliveryType": offer.delivery_type,
            "status": offer.status,
        }

        for offer in offers
    ]

# =========================================================
# UPDATE DRAFT OFFER
# =========================================================

@router.patch(
    "/offers/{offer_id}"
)
def update_offer(
    offer_id: uuid.UUID,
    payload: OfferUpdate,

    db: Session = Depends(get_db),

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
                "Offer references a missing application."
            ),
        )

    # =====================================================
    # 3. PUBLISHER AUTHORIZATION
    # =====================================================

    try:

        require_publisher_permission(
            db=db,
            user=current_user,
            publisher_id=application.publisher_id,
            permission_code="offer.manage",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 4. ONLY DRAFT OFFERS MAY BE EDITED
    # =====================================================

    if offer.status != "draft":

        raise HTTPException(
            status_code=409,
            detail=(
                "Only draft offers can be edited."
            ),
        )

    fields_set = payload.model_fields_set

    if not fields_set:

        raise HTTPException(
            status_code=422,
            detail="No offer fields were supplied.",
        )

    # =====================================================
    # 5. BASIC FIELDS
    # =====================================================

    if "name" in fields_set:

        if payload.name is None:

            raise HTTPException(
                status_code=422,
                detail="Offer name cannot be null.",
            )

        offer.name = payload.name

    if "description" in fields_set:

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

    if "version_policy" in fields_set:

        if payload.version_policy is None:

            raise HTTPException(
                status_code=422,
                detail=(
                    "version_policy cannot be null."
                ),
            )

        new_version_policy = (
            payload.version_policy
        )

        # Switching away from pinned automatically
        # removes the old pin unless the caller has
        # explicitly supplied pinned_version_id.
        if (
            new_version_policy != "pinned"
            and
            "pinned_version_id"
            not in fields_set
        ):

            new_pinned_version_id = None

    if "pinned_version_id" in fields_set:

        new_pinned_version_id = (
            payload.pinned_version_id
        )

    try:

        validate_offer_version_policy(
            db=db,
            offer_application_id=application.id,
            version_policy=new_version_policy,
            pinned_version_id=new_pinned_version_id,
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

    if "auto_upgrade" in fields_set:

        if payload.auto_upgrade is None:

            raise HTTPException(
                status_code=422,
                detail=(
                    "auto_upgrade cannot be null."
                ),
            )

        offer.auto_upgrade = (
            payload.auto_upgrade
        )

    # =====================================================
    # 8. ENTITLEMENT TEMPLATE
    #
    # Supplied list replaces the COMPLETE template.
    # Safe because this endpoint only edits drafts.
    # =====================================================

    if "entitlements" in fields_set:

        if not payload.entitlements:

            raise HTTPException(
                status_code=422,
                detail=(
                    "Offer must define at least "
                    "one entitlement."
                ),
            )

        entitlement_codes = [
            item.code
            for item in payload.entitlements
        ]

        if (
            len(entitlement_codes)
            != len(set(entitlement_codes))
        ):

            raise HTTPException(
                status_code=422,
                detail=(
                    "Duplicate entitlement codes "
                    "are not allowed."
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
                select(OfferEntitlement)
                .where(
                    OfferEntitlement.offer_id
                    == offer.id
                )
            )
        )

        for entitlement in (
            existing_entitlements
        ):

            db.delete(entitlement)

        # Important: flush deletes before inserting
        # replacements because (offer_id, code)
        # has a unique constraint.
        db.flush()

        for item in payload.entitlements:

            db.add(
                OfferEntitlement(
                    offer_id=offer.id,
                    code=item.code,
                    value_json=item.value,
                    status="active",
                )
            )

    # =====================================================
    # 9. COMMIT
    # =====================================================

    db.commit()

    db.refresh(offer)

    entitlements = list(
        db.scalars(
            select(OfferEntitlement)
            .where(
                OfferEntitlement.offer_id
                == offer.id
            )
            .order_by(
                OfferEntitlement.code
            )
        )
    )

    # =====================================================
    # 10. RESPONSE
    # =====================================================

    return {
        "id":
            str(offer.id),

        "applicationId":
            str(offer.application_id),

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
            str(offer.pinned_version_id)
            if offer.pinned_version_id
            else None
        ),

        "autoUpgrade":
            offer.auto_upgrade,

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
            }

            for entitlement
            in entitlements
        ],

        "updatedAt":
            offer.updated_at,
    }

# =========================================================
# RETIRE OFFER
# =========================================================

@router.post(
    "/offers/{offer_id}/retire"
)
def retire_offer(
    offer_id: uuid.UUID,

    db: Session = Depends(get_db),

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
                "Offer references a missing application."
            ),
        )

    # =====================================================
    # 3. PUBLISHER AUTHORIZATION
    # =====================================================

    try:

        require_publisher_permission(
            db=db,
            user=current_user,
            publisher_id=application.publisher_id,
            permission_code="offer.manage",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 4. IDEMPOTENT RETIREMENT
    # =====================================================

    if offer.status == "retired":

        return {
            "status": "RETIRED",
            "offerId": str(offer.id),
        }

    # Only an active commercial offer can be retired.
    # Draft offers should either be edited or remain draft.
    if offer.status != "active":

        raise HTTPException(
            status_code=409,
            detail=(
                f"Offer cannot be retired "
                f"from status {offer.status}"
            ),
        )

    # =====================================================
    # 5. RETIRE
    # =====================================================

    offer.status = "retired"

    db.commit()

    db.refresh(offer)

    # =====================================================
    # 6. RESPONSE
    # =====================================================

    return {
        "status": "RETIRED",

        "offerId":
            str(offer.id),

        "applicationId":
            str(offer.application_id),

        "offerKey":
            offer.offer_key,

        "updatedAt":
            offer.updated_at,
    }