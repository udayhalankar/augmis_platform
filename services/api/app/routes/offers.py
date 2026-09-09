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