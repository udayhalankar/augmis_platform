from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.models.iam import (
    PublisherMembership,
    PublisherMembershipRole,
    Role,
    TenantMembership,
    TenantMembershipRole,
)


class MembershipSetupError(Exception):
    pass


def get_role(
    db: Session,
    scope_type: str,
    role_code: str
) -> Role:

    role = db.scalar(
        select(Role)
        .where(
            Role.scope_type == scope_type,
            Role.code == role_code
        )
    )

    if not role:

        raise MembershipSetupError(
            f"Required role not found: "
            f"{scope_type}/{role_code}. "
            f"Run RBAC seed first."
        )

    return role


def create_tenant_owner_membership(
    db: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID
) -> TenantMembership:

    membership = TenantMembership(
        tenant_id=tenant_id,
        user_id=user_id,
        status="active"
    )

    db.add(membership)

    db.flush()

    owner_role = get_role(
        db=db,
        scope_type="tenant",
        role_code="tenant_owner"
    )

    db.add(
        TenantMembershipRole(
            membership_id=membership.id,
            role_id=owner_role.id
        )
    )

    return membership


def create_publisher_owner_membership(
    db: Session,
    publisher_id: uuid.UUID,
    user_id: uuid.UUID
) -> PublisherMembership:

    membership = PublisherMembership(
        publisher_id=publisher_id,
        user_id=user_id,
        status="active"
    )

    db.add(membership)

    db.flush()

    owner_role = get_role(
        db=db,
        scope_type="publisher",
        role_code="publisher_owner"
    )

    db.add(
        PublisherMembershipRole(
            membership_id=membership.id,
            role_id=owner_role.id
        )
    )

    return membership