from fastapi import (
    APIRouter,
    Depends,
    HTTPException
)

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.db.session import get_db

from services.api.app.models.platform import (
    Tenant
)

from services.api.app.schemas.tenant import (
    TenantCreate,
    TenantResponse
)


router = APIRouter(
    prefix="/api/v1/tenants",
    tags=["Tenants"]
)


@router.post(
    "",
    response_model=TenantResponse,
    status_code=201
)
def create_tenant(
    payload: TenantCreate,
    db: Session = Depends(get_db)
):

    existing = db.scalar(
        select(Tenant)
        .where(
            Tenant.slug == payload.slug
        )
    )

    if existing:

        raise HTTPException(
            status_code=409,
            detail="Tenant slug already exists"
        )

    tenant = Tenant(
        name=payload.name,
        slug=payload.slug,
        status="active"
    )

    db.add(tenant)

    db.commit()

    db.refresh(tenant)

    return tenant


@router.get(
    "",
    response_model=list[TenantResponse]
)
def list_tenants(
    db: Session = Depends(get_db)
):

    return list(
        db.scalars(
            select(Tenant)
            .order_by(
                Tenant.name
            )
        )
    )