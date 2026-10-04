# services/api/app/routes/tenants.py
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

from services.api.app.db.session import get_db

from services.api.app.models.iam import (
    User
)

from services.api.app.models.platform import (
    Tenant
)

from services.api.app.schemas.tenant import (
    TenantCreate,
    TenantResponse
)

from services.api.app.services.membership_service import (
    MembershipSetupError,
    create_tenant_owner_membership
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

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    )
):

    existing = db.scalar(
        select(Tenant)
        .where(
            Tenant.slug
            == payload.slug
        )
    )

    if existing:

        raise HTTPException(
            status_code=409,
            detail="Tenant slug already exists"
        )

    try:

        tenant = Tenant(
            name=payload.name,
            slug=payload.slug,
            status="active"
        )

        db.add(tenant)

        db.flush()

        create_tenant_owner_membership(
            db=db,
            tenant_id=tenant.id,
            user_id=current_user.id
        )

        db.commit()

        db.refresh(tenant)

        return tenant

    except MembershipSetupError as error:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


@router.get(
    "",
    response_model=list[TenantResponse]
)
def list_tenants(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        get_current_user
    )
):

    from services.api.app.models.iam import (
        TenantMembership
    )

    tenants = db.scalars(
        select(Tenant)
        .join(
            TenantMembership,
            TenantMembership.tenant_id
            == Tenant.id
        )
        .where(
            TenantMembership.user_id
            == current_user.id,

            TenantMembership.status
            == "active"
        )
        .order_by(
            Tenant.name
        )
    )

    return list(tenants)