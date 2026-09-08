from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.db.session import get_db
from services.api.app.models.platform import Publisher
from services.api.app.schemas.publisher import (
    PublisherCreate,
    PublisherResponse,
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
    db: Session = Depends(get_db)
):

    existing = db.scalar(
        select(Publisher)
        .where(
            Publisher.slug == payload.slug
        )
    )

    if existing:

        raise HTTPException(
            status_code=409,
            detail="Publisher slug already exists"
        )

    publisher = Publisher(
        name=payload.name,
        slug=payload.slug
    )

    db.add(publisher)

    db.commit()

    db.refresh(publisher)

    return publisher


@router.get(
    "",
    response_model=list[PublisherResponse]
)
def list_publishers(
    db: Session = Depends(get_db)
):

    return list(
        db.scalars(
            select(Publisher)
            .order_by(Publisher.name)
        )
    )