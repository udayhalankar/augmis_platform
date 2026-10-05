# services/api/app/services/rbac_admin_service.py

from __future__ import annotations

import uuid

from sqlalchemy import (
    delete,
    select,
)

from sqlalchemy.orm import Session

from services.api.app.core.rbac_catalog import (
    VALID_SCOPE_TYPES,
    permission_scope,
    role_is_protected,
)

from services.api.app.models.iam import (
    Permission,
    Role,
    RolePermission,
)


class RbacAdminError(
    Exception
):

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


def _clean_scope_type(
    scope_type: str | None,
) -> str | None:

    if scope_type is None:

        return None

    clean_scope_type = str(
        scope_type
    ).strip().lower()

    if (
        clean_scope_type
        not in VALID_SCOPE_TYPES
    ):

        raise RbacAdminError(
            "Invalid RBAC scope type.",
            status_code=400,
        )

    return clean_scope_type


def _permission_payload(
    permission: Permission,
) -> dict:

    scope_type = (
        permission_scope(
            permission.code
        )
    )

    if not scope_type:

        raise RbacAdminError(
            (
                "Permission is not present "
                "in the canonical RBAC "
                "catalogue: "
                f"{permission.code}"
            ),
            status_code=409,
        )

    return {

        "id":
            permission.id,

        "code":
            permission.code,

        "name":
            permission.name,

        "scopeType":
            scope_type,
    }


def _role_permissions(
    db: Session,
    role_id: uuid.UUID,
) -> list[Permission]:

    return list(
        db.scalars(
            select(
                Permission
            )
            .join(
                RolePermission,
                RolePermission.permission_id
                == Permission.id,
            )
            .where(
                RolePermission.role_id
                == role_id,
            )
            .order_by(
                Permission.code
            )
        )
    )


def role_payload(
    db: Session,
    role: Role,
) -> dict:

    permissions = (
        _role_permissions(
            db=db,
            role_id=role.id,
        )
    )

    return {

        "id":
            role.id,

        "scopeType":
            role.scope_type,

        "code":
            role.code,

        "name":
            role.name,

        "protected":
            role_is_protected(
                role.scope_type,
                role.code,
            ),

        "permissions": [
            _permission_payload(
                permission
            )
            for permission
            in permissions
        ],
    }


def list_permissions(
    db: Session,
    *,
    scope_type: str | None = None,
) -> list[dict]:

    clean_scope_type = (
        _clean_scope_type(
            scope_type
        )
    )

    permissions = list(
        db.scalars(
            select(
                Permission
            )
            .order_by(
                Permission.code
            )
        )
    )

    result: list[dict] = []

    for permission in permissions:

        payload = (
            _permission_payload(
                permission
            )
        )

        if (
            clean_scope_type
            and payload[
                "scopeType"
            ]
            != clean_scope_type
        ):

            continue

        result.append(
            payload
        )

    return result


def list_roles(
    db: Session,
    *,
    scope_type: str | None = None,
) -> list[dict]:

    clean_scope_type = (
        _clean_scope_type(
            scope_type
        )
    )

    statement = (
        select(
            Role
        )
        .order_by(
            Role.scope_type,
            Role.name,
            Role.code,
        )
    )

    if clean_scope_type:

        statement = (
            statement.where(
                Role.scope_type
                == clean_scope_type
            )
        )

    roles = list(
        db.scalars(
            statement
        )
    )

    return [
        role_payload(
            db=db,
            role=role,
        )
        for role in roles
    ]


def replace_role_permissions(
    db: Session,
    *,
    role_id: uuid.UUID,
    permission_codes: list[str],
) -> tuple[
    Role,
    list[str],
    list[str],
]:

    role = db.get(
        Role,
        role_id,
    )

    if not role:

        raise RbacAdminError(
            "RBAC role not found.",
            status_code=404,
        )


    # --------------------------------------------------------
    # PROTECTED OWNER ROLES
    # --------------------------------------------------------

    if role_is_protected(
        role.scope_type,
        role.code,
    ):

        raise RbacAdminError(
            (
                "Protected owner roles "
                "cannot be modified through "
                "the RBAC administration API."
            ),
            status_code=409,
        )


    # --------------------------------------------------------
    # NORMALIZE REQUESTED PERMISSION CODES
    # --------------------------------------------------------

    normalized_codes: list[str] = []

    seen_codes: set[str] = set()

    for value in permission_codes:

        code = str(
            value or ""
        ).strip()

        if not code:

            continue

        if code in seen_codes:

            continue

        seen_codes.add(
            code
        )

        normalized_codes.append(
            code
        )


    if not normalized_codes:

        raise RbacAdminError(
            "At least one permission is required.",
            status_code=400,
        )


    # --------------------------------------------------------
    # VERIFY PERMISSION SCOPE
    # --------------------------------------------------------

    invalid_scope_codes = [

        code

        for code in normalized_codes

        if permission_scope(
            code
        )
        != role.scope_type
    ]


    if invalid_scope_codes:

        raise RbacAdminError(
            (
                "Permission scope does not "
                "match role scope: "
                + ", ".join(
                    invalid_scope_codes
                )
            ),
            status_code=400,
        )


    # --------------------------------------------------------
    # LOAD DB PERMISSION RECORDS
    # --------------------------------------------------------

    permissions = list(
        db.scalars(
            select(
                Permission
            )
            .where(
                Permission.code.in_(
                    normalized_codes
                )
            )
        )
    )


    permission_map = {

        permission.code:
            permission

        for permission
        in permissions
    }


    missing_codes = [

        code

        for code
        in normalized_codes

        if code
        not in permission_map
    ]


    if missing_codes:

        raise RbacAdminError(
            (
                "Unknown permission code(s): "
                + ", ".join(
                    missing_codes
                )
            ),
            status_code=400,
        )


    # --------------------------------------------------------
    # CAPTURE EXISTING PERMISSIONS FOR AUDIT
    # --------------------------------------------------------

    previous_permissions = (
        _role_permissions(
            db=db,
            role_id=role.id,
        )
    )


    previous_codes = [

        permission.code

        for permission
        in previous_permissions
    ]


    # --------------------------------------------------------
    # REMOVE OLD MAPPINGS
    # --------------------------------------------------------

    db.execute(
        delete(
            RolePermission
        )
        .where(
            RolePermission.role_id
            == role.id
        )
    )


    db.flush()


    # --------------------------------------------------------
    # CREATE NEW MAPPINGS
    # --------------------------------------------------------

    for code in normalized_codes:

        permission = (
            permission_map[
                code
            ]
        )

        db.add(
            RolePermission(
                role_id=
                    role.id,

                permission_id=
                    permission.id,
            )
        )


    db.flush()


    return (
        role,
        sorted(
            previous_codes
        ),
        sorted(
            normalized_codes
        ),
    )