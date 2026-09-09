from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.models.iam import (
    Permission,
    PublisherMembership,
    PublisherMembershipRole,
    Role,
    RolePermission,
    TenantMembership,
    TenantMembershipRole,
    User,
)


class AuthorizationError(Exception):
    pass


def get_tenant_membership(
    db: Session,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID
) -> TenantMembership | None:

    return db.scalar(
        select(TenantMembership)
        .where(
            TenantMembership.user_id == user_id,
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.status == "active"
        )
    )


def get_publisher_membership(
    db: Session,
    user_id: uuid.UUID,
    publisher_id: uuid.UUID
) -> PublisherMembership | None:

    return db.scalar(
        select(PublisherMembership)
        .where(
            PublisherMembership.user_id == user_id,
            PublisherMembership.publisher_id == publisher_id,
            PublisherMembership.status == "active"
        )
    )


def get_tenant_permissions(
    db: Session,
    membership_id: uuid.UUID
) -> set[str]:

    rows = db.execute(
        select(Permission.code)
        .join(
            RolePermission,
            RolePermission.permission_id
            == Permission.id
        )
        .join(
            TenantMembershipRole,
            TenantMembershipRole.role_id
            == RolePermission.role_id
        )
        .where(
            TenantMembershipRole.membership_id
            == membership_id
        )
    ).all()

    return {
        row[0]
        for row in rows
    }


def get_publisher_permissions(
    db: Session,
    membership_id: uuid.UUID
) -> set[str]:

    rows = db.execute(
        select(Permission.code)
        .join(
            RolePermission,
            RolePermission.permission_id
            == Permission.id
        )
        .join(
            PublisherMembershipRole,
            PublisherMembershipRole.role_id
            == RolePermission.role_id
        )
        .where(
            PublisherMembershipRole.membership_id
            == membership_id
        )
    ).all()

    return {
        row[0]
        for row in rows
    }


def require_tenant_permission(
    db: Session,
    user: User,
    tenant_id: uuid.UUID,
    permission_code: str
) -> TenantMembership:

    membership = get_tenant_membership(
        db=db,
        user_id=user.id,
        tenant_id=tenant_id
    )

    if not membership:

        raise AuthorizationError(
            "You do not belong to this tenant."
        )

    permissions = get_tenant_permissions(
        db=db,
        membership_id=membership.id
    )

    if permission_code not in permissions:

        raise AuthorizationError(
            f"Missing tenant permission: "
            f"{permission_code}"
        )

    return membership


def require_publisher_permission(
    db: Session,
    user: User,
    publisher_id: uuid.UUID,
    permission_code: str
) -> PublisherMembership:

    membership = get_publisher_membership(
        db=db,
        user_id=user.id,
        publisher_id=publisher_id
    )

    if not membership:

        raise AuthorizationError(
            "You do not belong to this publisher."
        )

    permissions = get_publisher_permissions(
        db=db,
        membership_id=membership.id
    )

    if permission_code not in permissions:

        raise AuthorizationError(
            f"Missing publisher permission: "
            f"{permission_code}"
        )

    return membership