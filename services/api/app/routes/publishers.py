from fastapi import (
    APIRouter,
    Depends,
    HTTPException
)

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.core.auth import (
    get_current_user
)

from services.api.app.db.session import (
    get_db
)

from services.api.app.models.iam import (
    PublisherMembership,
    User
)

from services.api.app.models.platform import (
    Publisher
)

from services.api.app.schemas.publisher import (
    PublisherCreate,
    PublisherResponse
)

from services.api.app.services.authorization_service import (
    AuthorizationError,
    require_platform_permission,
)

from services.api.app.services.membership_service import (
    MembershipSetupError,
    create_publisher_owner_membership
)


router = APIRouter(
    prefix="/api/v1/publishers",
    tags=["Publishers"]
)


@router.post(
    "",
    response_model=PublisherResponse,
    status_code=201
)
def create_publisher(
    payload: PublisherCreate,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    )
):

    try:
        require_platform_permission(
            db=db,
            user=current_user,
            permission_code="platform.publishers.manage",
        )

    except AuthorizationError as error:
        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    existing = db.scalar(
        select(Publisher)
        .where(
            Publisher.slug
            == payload.slug
        )
    )

    if existing:

        raise HTTPException(
            status_code=409,
            detail="Publisher slug already exists"
        )

    try:

        publisher = Publisher(
            name=payload.name,
            slug=payload.slug,
            status="active"
        )

        db.add(publisher)

        db.flush()

        create_publisher_owner_membership(
            db=db,
            publisher_id=publisher.id,
            user_id=current_user.id
        )

        db.commit()

        db.refresh(publisher)

        return publisher

    except MembershipSetupError as error:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


@router.get(
    "",
    response_model=list[PublisherResponse]
)
def list_publishers(
    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    )
):

    publishers = db.scalars(
        select(Publisher)
        .join(
            PublisherMembership,
            PublisherMembership.publisher_id
            == Publisher.id
        )
        .where(
            PublisherMembership.user_id
            == current_user.id,

            PublisherMembership.status
            == "active"
        )
        .order_by(
            Publisher.name
        )
    )

    return list(publishers)