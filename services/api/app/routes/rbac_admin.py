# services/api/app/routes/rbac_admin.py

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)

from sqlalchemy.orm import Session

from services.api.app.core.auth import (
    get_current_user,
)

from services.api.app.db.session import (
    get_db,
)

from services.api.app.models.iam import (
    User,
)

from services.api.app.schemas.rbac_admin import (
    EffectivePermissionResponse,
    RbacPermissionResponse,
    RbacRolePermissionUpdateRequest,
    RbacRoleResponse,
)

from services.api.app.services.audit_service import (
    record_audit_event,
)

from services.api.app.services.authorization_service import (
    AuthorizationError,
    get_platform_permissions,
    get_tenant_membership,
    get_tenant_permissions,
    require_platform_permission,
)

from services.api.app.services.rbac_admin_service import (
    RbacAdminError,
    list_permissions,
    list_roles,
    replace_role_permissions,
    role_payload,
)


router = APIRouter(
    prefix="/api/v1",
    tags=[
        "RBAC Administration"
    ],
)


# ============================================================
# PLATFORM RBAC ADMIN AUTHORIZATION
# ============================================================


def _require_platform_rbac_admin(
    *,
    db: Session,
    current_user: User,
) -> None:

    try:

        require_platform_permission(
            db=db,

            user=current_user,

            permission_code=(
                "platform.rbac.manage"
            ),
        )


    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error


def _raise_rbac_error(
    error: RbacAdminError,
) -> None:

    raise HTTPException(
        status_code=error.status_code,
        detail=str(error),
    ) from error


# ============================================================
# CURRENT USER — PLATFORM PERMISSIONS
# ============================================================


@router.get(
    "/auth/permissions",
    response_model=(
        EffectivePermissionResponse
    ),
)
def my_platform_permissions(
    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    permissions = sorted(
        get_platform_permissions(
            db=db,
            user_id=current_user.id,
        )
    )


    return {

        "scopeType":
            "platform",

        "permissions":
            permissions,
    }


# ============================================================
# CURRENT USER — TENANT PERMISSIONS
# ============================================================


@router.get(
    "/tenants/{tenant_id}/me/permissions",
    response_model=(
        EffectivePermissionResponse
    ),
)
def my_tenant_permissions(
    tenant_id: uuid.UUID,

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    membership = (
        get_tenant_membership(
            db=db,

            user_id=
                current_user.id,

            tenant_id=
                tenant_id,
        )
    )


    if not membership:

        raise HTTPException(
            status_code=403,
            detail=(
                "You do not belong "
                "to this tenant."
            ),
        )


    permissions = sorted(
        get_tenant_permissions(
            db=db,
            membership_id=(
                membership.id
            ),
        )
    )


    return {

        "scopeType":
            "tenant",

        "permissions":
            permissions,
    }


# ============================================================
# PERMISSION CATALOGUE
# ============================================================


@router.get(
    "/rbac/permissions",
    response_model=list[
        RbacPermissionResponse
    ],
)
def get_rbac_permissions(
    scope_type: str | None = Query(
        default=None,
        alias="scopeType",
    ),

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    _require_platform_rbac_admin(
        db=db,
        current_user=current_user,
    )


    try:

        return list_permissions(
            db=db,
            scope_type=scope_type,
        )


    except RbacAdminError as error:

        _raise_rbac_error(
            error
        )


# ============================================================
# ROLE CATALOGUE
# ============================================================


@router.get(
    "/rbac/roles",
    response_model=list[
        RbacRoleResponse
    ],
)
def get_rbac_roles(
    scope_type: str | None = Query(
        default=None,
        alias="scopeType",
    ),

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    _require_platform_rbac_admin(
        db=db,
        current_user=current_user,
    )


    try:

        return list_roles(
            db=db,
            scope_type=scope_type,
        )


    except RbacAdminError as error:

        _raise_rbac_error(
            error
        )


# ============================================================
# ROLE → PERMISSION ASSIGNMENT
# ============================================================


@router.put(
    "/rbac/roles/"
    "{role_id}/permissions",
    response_model=(
        RbacRoleResponse
    ),
)
def update_role_permissions(
    role_id: uuid.UUID,

    payload:
        RbacRolePermissionUpdateRequest,

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    _require_platform_rbac_admin(
        db=db,
        current_user=current_user,
    )


    try:

        (
            role,
            previous_codes,
            new_codes,
        ) = (
            replace_role_permissions(
                db=db,

                role_id=
                    role_id,

                permission_codes=(
                    payload
                    .permission_codes
                ),
            )
        )


        record_audit_event(
            db,

            action=(
                "platform.rbac."
                "role.permissions.update"
            ),

            resource_type=(
                "iam_role"
            ),

            resource_id=(
                role.id
            ),

            actor_user_id=(
                current_user.id
            ),

            outcome="success",

            message=(
                "RBAC role permissions updated."
            ),

            metadata={

                "scopeType":
                    role.scope_type,

                "roleCode":
                    role.code,

                "previousPermissionCodes":
                    previous_codes,

                "permissionCodes":
                    new_codes,
            },
        )


        db.commit()


        return role_payload(
            db=db,
            role=role,
        )


    except RbacAdminError as error:

        db.rollback()

        _raise_rbac_error(
            error
        )