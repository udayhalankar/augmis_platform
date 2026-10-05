# services/api/app/services/tenant_user_service.py

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.core.rbac_catalog import (
    role_is_protected,
)

from services.api.app.models.iam import (
    Role,
    TenantMembership,
    TenantMembershipRole,
    User,
)

from services.api.app.services.audit_service import (
    record_audit_event,
)

from services.api.app.services.auth_service import (
    normalize_email,
)

from services.api.app.services.authorization_service import (
    AuthorizationError,
    require_protected_tenant_role_manager,
)


class TenantUserServiceError(Exception):

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
    ) -> None:

        super().__init__(
            message
        )

        self.status_code = (
            status_code
        )


def _role_payload(
    role: Role,
) -> dict:

    return {
        "id":
            role.id,

        "code":
            role.code,

        "name":
            role.name,
    }


def _user_payload(
    user: User,
) -> dict:

    return {
        "id":
            user.id,

        "email":
            user.email,

        "firstName":
            user.first_name,

        "lastName":
            user.last_name,

        "status":
            user.status,
    }


def _membership_roles(
    db: Session,
    membership_id: uuid.UUID,
) -> list[Role]:

    return list(
        db.scalars(
            select(
                Role
            )
            .join(
                TenantMembershipRole,
                TenantMembershipRole.role_id
                == Role.id,
            )
            .where(
                TenantMembershipRole.membership_id
                == membership_id,
            )
            .order_by(
                Role.name,
                Role.code,
            )
        )
    )


def _membership_payload(
    db: Session,
    membership: TenantMembership,
    user: User,
) -> dict:

    roles = (
        _membership_roles(
            db=db,
            membership_id=membership.id,
        )
    )

    return {
        "membershipId":
            membership.id,

        "status":
            membership.status,

        "createdAt":
            membership.created_at,

        "user":
            _user_payload(
                user
            ),

        "roles": [
            _role_payload(
                role
            )
            for role in roles
        ],
    }


def _get_membership_for_tenant(
    db: Session,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
) -> TenantMembership:

    membership = db.scalar(
        select(
            TenantMembership
        )
        .where(
            TenantMembership.id
            == membership_id,

            TenantMembership.tenant_id
            == tenant_id,
        )
    )

    if not membership:

        raise TenantUserServiceError(
            "Tenant membership not found.",
            status_code=404,
        )

    return membership


def _get_user(
    db: Session,
    user_id: uuid.UUID,
) -> User:

    user = db.get(
        User,
        user_id,
    )

    if not user:

        raise TenantUserServiceError(
            "Membership references a missing user.",
            status_code=409,
        )

    return user


def _normalize_role_codes(
    role_codes: list[str],
) -> list[str]:

    normalized: list[str] = []

    seen: set[str] = set()

    for value in role_codes:

        code = str(
            value or ""
        ).strip()

        if (
            not code
            or code in seen
        ):
            continue

        seen.add(
            code
        )

        normalized.append(
            code
        )

    if not normalized:

        raise TenantUserServiceError(
            "At least one tenant role is required.",
            status_code=400,
        )

    return normalized


def _resolve_tenant_roles(
    db: Session,
    role_codes: list[str],
) -> list[Role]:

    normalized_codes = (
        _normalize_role_codes(
            role_codes
        )
    )

    roles = list(
        db.scalars(
            select(
                Role
            )
            .where(
                Role.scope_type
                == "tenant",

                Role.code.in_(
                    normalized_codes
                ),
            )
        )
    )

    role_map = {
        role.code:
            role
        for role in roles
    }

    missing_codes = [
        code
        for code in normalized_codes
        if code not in role_map
    ]

    if missing_codes:

        raise TenantUserServiceError(
            (
                "Invalid tenant role code(s): "
                + ", ".join(
                    missing_codes
                )
            ),
            status_code=400,
        )

    return [
        role_map[
            code
        ]
        for code in normalized_codes
    ]


def _membership_has_role(
    db: Session,
    membership_id: uuid.UUID,
    role_code: str,
) -> bool:

    role_id = db.scalar(
        select(
            Role.id
        )
        .join(
            TenantMembershipRole,
            TenantMembershipRole.role_id
            == Role.id,
        )
        .where(
            TenantMembershipRole.membership_id
            == membership_id,

            Role.scope_type
            == "tenant",

            Role.code
            == role_code,
        )
        .limit(
            1
        )
    )

    return (
        role_id
        is not None
    )



def _roles_include_protected_tenant_role(
    roles: list[Role],
) -> bool:

    return any(
        role_is_protected(
            "tenant",
            role.code,
        )
        for role in roles
    )


def _membership_has_protected_tenant_role(
    db: Session,
    membership_id: uuid.UUID,
) -> bool:

    return _roles_include_protected_tenant_role(
        _membership_roles(
            db=db,
            membership_id=membership_id,
        )
    )


def _require_actor_can_manage_protected_tenant_roles(
    db: Session,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> None:

    try:
        require_protected_tenant_role_manager(
            db=db,
            user_id=actor_user_id,
            tenant_id=tenant_id,
        )

    except AuthorizationError as error:
        raise TenantUserServiceError(
            str(error),
            status_code=403,
        ) from error

def _has_other_active_owner(
    db: Session,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
) -> bool:

    other_owner_id = db.scalar(
        select(
            TenantMembership.id
        )
        .join(
            TenantMembershipRole,
            TenantMembershipRole.membership_id
            == TenantMembership.id,
        )
        .join(
            Role,
            Role.id
            == TenantMembershipRole.role_id,
        )
        .where(
            TenantMembership.tenant_id
            == tenant_id,

            TenantMembership.status
            == "active",

            TenantMembership.id
            != membership_id,

            Role.scope_type
            == "tenant",

            Role.code
            == "tenant_owner",
        )
        .limit(
            1
        )
    )

    return (
        other_owner_id
        is not None
    )


def _protect_last_active_owner(
    db: Session,
    membership: TenantMembership,
) -> None:

    if (
        membership.status
        != "active"
    ):
        return

    if not _membership_has_role(
        db=db,
        membership_id=membership.id,
        role_code="tenant_owner",
    ):
        return

    if _has_other_active_owner(
        db=db,
        tenant_id=membership.tenant_id,
        membership_id=membership.id,
    ):
        return

    raise TenantUserServiceError(
        (
            "This membership is the tenant's "
            "last active Tenant Owner and cannot "
            "be changed in a way that removes "
            "active owner access."
        ),
        status_code=409,
    )


def list_tenant_users(
    db: Session,
    tenant_id: uuid.UUID,
) -> list[dict]:

    rows = db.execute(
        select(
            TenantMembership,
            User,
        )
        .join(
            User,
            User.id
            == TenantMembership.user_id,
        )
        .where(
            TenantMembership.tenant_id
            == tenant_id,
        )
        .order_by(
            User.last_name,
            User.first_name,
            User.email_normalized,
        )
    ).all()

    return [
        _membership_payload(
            db=db,
            membership=membership,
            user=user,
        )
        for (
            membership,
            user
        ) in rows
    ]


def list_tenant_roles(
    db: Session,
) -> list[dict]:

    roles = list(
        db.scalars(
            select(
                Role
            )
            .where(
                Role.scope_type
                == "tenant",
            )
            .order_by(
                Role.name,
                Role.code,
            )
        )
    )

    return [
        _role_payload(
            role
        )
        for role in roles
    ]


def add_existing_user_to_tenant(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    email: str,
    role_codes: list[str],
) -> dict:

    normalized_email = (
        normalize_email(
            email
        )
    )

    user = db.scalar(
        select(
            User
        )
        .where(
            User.email_normalized
            == normalized_email,
        )
    )

    if not user:

        raise TenantUserServiceError(
            (
                "No AUGMIS user is registered "
                "with this email address."
            ),
            status_code=404,
        )

    if (
        user.status
        != "active"
    ):

        raise TenantUserServiceError(
            "The AUGMIS user account is not active.",
            status_code=409,
        )

    existing_membership = (
        db.scalar(
            select(
                TenantMembership
            )
            .where(
                TenantMembership.tenant_id
                == tenant_id,

                TenantMembership.user_id
                == user.id,
            )
        )
    )

    if existing_membership:

        raise TenantUserServiceError(
            (
                "This user already has a tenant "
                f"membership with status "
                f"'{existing_membership.status}'."
            ),
            status_code=409,
        )

    roles = (
        _resolve_tenant_roles(
            db=db,
            role_codes=role_codes,
        )
    )

    if _roles_include_protected_tenant_role(
        roles
    ):
        _require_actor_can_manage_protected_tenant_roles(
            db=db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
        )

    membership = (
        TenantMembership(
            tenant_id=tenant_id,
            user_id=user.id,
            status="active",
        )
    )

    db.add(
        membership
    )

    db.flush()

    for role in roles:

        db.add(
            TenantMembershipRole(
                membership_id=membership.id,
                role_id=role.id,
            )
        )

    db.flush()

    record_audit_event(
        db,
        action="tenant.user.add",
        resource_type="tenant_membership",
        resource_id=membership.id,
        actor_user_id=actor_user_id,
        tenant_id=tenant_id,
        outcome="success",
        message=(
            f"Added {user.email} to tenant."
        ),
        metadata={
            "targetUserId":
                str(user.id),

            "targetEmail":
                user.email,

            "roleCodes": [
                role.code
                for role in roles
            ],
        },
    )

    db.commit()

    db.refresh(
        membership
    )

    return _membership_payload(
        db=db,
        membership=membership,
        user=user,
    )


def replace_membership_roles(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    role_codes: list[str],
) -> dict:

    membership = (
        _get_membership_for_tenant(
            db=db,
            tenant_id=tenant_id,
            membership_id=membership_id,
        )
    )

    if (
        membership.status
        == "revoked"
    ):

        raise TenantUserServiceError(
            (
                "A revoked membership must be "
                "reactivated before its roles "
                "can be changed."
            ),
            status_code=409,
        )

    user = _get_user(
        db=db,
        user_id=membership.user_id,
    )

    new_roles = (
        _resolve_tenant_roles(
            db=db,
            role_codes=role_codes,
        )
    )

    previous_roles = (
        _membership_roles(
            db=db,
            membership_id=membership.id,
        )
    )

    if (
        _roles_include_protected_tenant_role(
            previous_roles
        )
        or _roles_include_protected_tenant_role(
            new_roles
        )
    ):
        _require_actor_can_manage_protected_tenant_roles(
            db=db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
        )

    previous_codes = {
        role.code
        for role in previous_roles
    }

    new_codes = {
        role.code
        for role in new_roles
    }

    if (
        "tenant_owner"
        in previous_codes
        and "tenant_owner"
        not in new_codes
    ):

        _protect_last_active_owner(
            db=db,
            membership=membership,
        )

    existing_assignments = list(
        db.scalars(
            select(
                TenantMembershipRole
            )
            .where(
                TenantMembershipRole.membership_id
                == membership.id,
            )
        )
    )

    for assignment in existing_assignments:

        db.delete(
            assignment
        )

    db.flush()

    for role in new_roles:

        db.add(
            TenantMembershipRole(
                membership_id=membership.id,
                role_id=role.id,
            )
        )

    db.flush()

    record_audit_event(
        db,
        action="tenant.user.roles.update",
        resource_type="tenant_membership",
        resource_id=membership.id,
        actor_user_id=actor_user_id,
        tenant_id=tenant_id,
        outcome="success",
        message=(
            f"Updated tenant roles for {user.email}."
        ),
        metadata={
            "targetUserId":
                str(user.id),

            "targetEmail":
                user.email,

            "previousRoleCodes":
                sorted(
                    previous_codes
                ),

            "roleCodes":
                sorted(
                    new_codes
                ),
        },
    )

    db.commit()

    db.refresh(
        membership
    )

    return _membership_payload(
        db=db,
        membership=membership,
        user=user,
    )


def set_membership_status(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    new_status: str,
) -> dict:

    if new_status not in {
        "active",
        "suspended",
        "revoked",
    }:

        raise TenantUserServiceError(
            "Invalid tenant membership status.",
            status_code=400,
        )

    membership = (
        _get_membership_for_tenant(
            db=db,
            tenant_id=tenant_id,
            membership_id=membership_id,
        )
    )

    user = _get_user(
        db=db,
        user_id=membership.user_id,
    )

    previous_status = (
        membership.status
    )

    if (
        previous_status
        == new_status
    ):

        return _membership_payload(
            db=db,
            membership=membership,
            user=user,
        )

    if _membership_has_protected_tenant_role(
        db=db,
        membership_id=membership.id,
    ):
        _require_actor_can_manage_protected_tenant_roles(
            db=db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
        )

    if new_status in {
        "suspended",
        "revoked",
    }:

        _protect_last_active_owner(
            db=db,
            membership=membership,
        )

    membership.status = (
        new_status
    )

    db.flush()

    action_map = {
        "active":
            "tenant.user.activate",

        "suspended":
            "tenant.user.suspend",

        "revoked":
            "tenant.user.revoke",
    }

    record_audit_event(
        db,
        action=action_map[
            new_status
        ],
        resource_type="tenant_membership",
        resource_id=membership.id,
        actor_user_id=actor_user_id,
        tenant_id=tenant_id,
        outcome="success",
        message=(
            f"Tenant membership for {user.email} "
            f"changed from {previous_status} "
            f"to {new_status}."
        ),
        metadata={
            "targetUserId":
                str(user.id),

            "targetEmail":
                user.email,

            "previousStatus":
                previous_status,

            "status":
                new_status,
        },
    )

    db.commit()

    db.refresh(
        membership
    )

    return _membership_payload(
        db=db,
        membership=membership,
        user=user,
    )
