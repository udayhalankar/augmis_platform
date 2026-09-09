from fastapi import (
    APIRouter,
    Depends
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
    TenantMembership,
    User
)

from services.api.app.models.platform import (
    Publisher,
    Tenant
)


router = APIRouter(
    prefix="/api/v1/me",
    tags=["Memberships"]
)


@router.get(
    "/tenants"
)
def my_tenants(
    current_user: User = Depends(
        get_current_user
    ),

    db: Session = Depends(get_db)
):

    rows = db.execute(
        select(
            TenantMembership,
            Tenant
        )
        .join(
            Tenant,
            Tenant.id
            == TenantMembership.tenant_id
        )
        .where(
            TenantMembership.user_id
            == current_user.id
        )
        .order_by(
            Tenant.name
        )
    ).all()

    return [
        {
            "membershipId":
                str(membership.id),

            "tenant": {
                "id":
                    str(tenant.id),

                "name":
                    tenant.name,

                "slug":
                    tenant.slug
            },

            "status":
                membership.status
        }

        for membership, tenant in rows
    ]


@router.get(
    "/publishers"
)
def my_publishers(
    current_user: User = Depends(
        get_current_user
    ),

    db: Session = Depends(get_db)
):

    rows = db.execute(
        select(
            PublisherMembership,
            Publisher
        )
        .join(
            Publisher,
            Publisher.id
            == PublisherMembership.publisher_id
        )
        .where(
            PublisherMembership.user_id
            == current_user.id
        )
        .order_by(
            Publisher.name
        )
    ).all()

    return [
        {
            "membershipId":
                str(membership.id),

            "publisher": {
                "id":
                    str(publisher.id),

                "name":
                    publisher.name,

                "slug":
                    publisher.slug
            },

            "status":
                membership.status
        }

        for membership, publisher in rows
    ]