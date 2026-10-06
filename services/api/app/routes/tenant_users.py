# services/api/app/routes/tenant_users.py

import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
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

from services.api.app.models.platform import (
    Tenant,
)

from services.api.app.schemas.tenant_user import (
    TenantOwnerRecoveryRequest,
    TenantRoleResponse,
    TenantUserAddRequest,
    TenantUserMembershipResponse,
    TenantUserRoleUpdateRequest,
)

from services.api.app.services.authorization_service import (
    AuthorizationError,
    require_any_tenant_permission,
    require_platform_permission,
    require_tenant_permission,
)

from services.api.app.services.tenant_user_service import (
    TenantUserServiceError,
    add_existing_user_to_tenant,
    list_tenant_roles,
    list_tenant_users,
    recover_orphan_tenant_owner,
    replace_membership_roles,
    set_membership_status,
)


router = APIRouter(
    prefix="/api/v1/tenants",
    tags=["Tenant Users"],
)


# ============================================================
# TENANT RESOLUTION
# ============================================================


def _load_tenant(
    *,
    db: Session,
    tenant_id: uuid.UUID,
) -> Tenant:

    tenant = db.get(
        Tenant,
        tenant_id,
    )

    if not tenant:

        raise HTTPException(
            status_code=404,
            detail="Tenant not found",
        )

    return tenant


# ============================================================
# TENANT USERS — READ AUTHORIZATION
# ============================================================


def _require_tenant_user_view(
    *,
    db: Session,
    current_user: User,
    tenant_id: uuid.UUID,
) -> Tenant:

    tenant = (
        _load_tenant(
            db=db,
            tenant_id=tenant_id,
        )
    )


    try:

        require_any_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=tenant.id,
            permission_codes={
                "tenant.users.view",
                "tenant.users.manage",
            },
        )


    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error


    return tenant


# ============================================================
# TENANT USERS — MANAGEMENT AUTHORIZATION
# ============================================================


def _require_tenant_user_management(
    *,
    db: Session,
    current_user: User,
    tenant_id: uuid.UUID,
) -> Tenant:

    tenant = (
        _load_tenant(
            db=db,
            tenant_id=tenant_id,
        )
    )


    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=tenant.id,
            permission_code=(
                "tenant.users.manage"
            ),
        )


    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error


    return tenant


# ============================================================
# SERVICE ERROR MAPPING
# ============================================================


def _raise_service_error(
    error: TenantUserServiceError,
) -> None:

    raise HTTPException(
        status_code=error.status_code,
        detail=str(error),
    ) from error


# ============================================================
# LIST TENANT USERS
# ============================================================


@router.get(
    "/{tenant_id}/users",
    response_model=list[
        TenantUserMembershipResponse
    ],
)
def get_tenant_users(
    tenant_id: uuid.UUID,

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    _require_tenant_user_view(
        db=db,
        current_user=current_user,
        tenant_id=tenant_id,
    )


    return list_tenant_users(
        db=db,
        tenant_id=tenant_id,
    )


# ============================================================
# LIST TENANT ROLES
# ============================================================


@router.get(
    "/{tenant_id}/roles",
    response_model=list[
        TenantRoleResponse
    ],
)
def get_tenant_roles(
    tenant_id: uuid.UUID,

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    _require_tenant_user_view(
        db=db,
        current_user=current_user,
        tenant_id=tenant_id,
    )


    return list_tenant_roles(
        db=db,
    )


# ============================================================
# ADD EXISTING AUGMIS USER
# ============================================================


@router.post(
    "/{tenant_id}/users",
    response_model=(
        TenantUserMembershipResponse
    ),
    status_code=201,
)
def add_tenant_user(
    tenant_id: uuid.UUID,

    payload: TenantUserAddRequest,

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    _require_tenant_user_management(
        db=db,
        current_user=current_user,
        tenant_id=tenant_id,
    )


    try:

        return (
            add_existing_user_to_tenant(
                db=db,

                tenant_id=tenant_id,

                actor_user_id=(
                    current_user.id
                ),

                email=str(
                    payload.email
                ),

                role_codes=(
                    payload.role_codes
                ),
            )
        )


    except TenantUserServiceError as error:

        db.rollback()

        _raise_service_error(
            error
        )

# ============================================================
# PLATFORM ORPHAN-OWNER RECOVERY
# ============================================================


@router.post(
    "/{tenant_id}/owner-recovery",
    response_model=(
        TenantUserMembershipResponse
    ),
)
def recover_tenant_owner(
    tenant_id: uuid.UUID,

    payload: TenantOwnerRecoveryRequest,

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

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

    try:

        return recover_orphan_tenant_owner(
            db=db,
            tenant_id=tenant_id,
            actor_user_id=(
                current_user.id
            ),
            email=str(
                payload.email
            ),
        )

    except TenantUserServiceError as error:

        db.rollback()

        _raise_service_error(
            error
        )

# ============================================================
# REPLACE MEMBERSHIP ROLES
# ============================================================


@router.put(
    "/{tenant_id}/memberships/"
    "{membership_id}/roles",
    response_model=(
        TenantUserMembershipResponse
    ),
)
def update_tenant_user_roles(
    tenant_id: uuid.UUID,

    membership_id: uuid.UUID,

    payload:
        TenantUserRoleUpdateRequest,

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    _require_tenant_user_management(
        db=db,
        current_user=current_user,
        tenant_id=tenant_id,
    )


    try:

        return (
            replace_membership_roles(
                db=db,

                tenant_id=tenant_id,

                membership_id=(
                    membership_id
                ),

                actor_user_id=(
                    current_user.id
                ),

                role_codes=(
                    payload.role_codes
                ),
            )
        )


    except TenantUserServiceError as error:

        db.rollback()

        _raise_service_error(
            error
        )


# ============================================================
# SUSPEND MEMBERSHIP
# ============================================================


@router.post(
    "/{tenant_id}/memberships/"
    "{membership_id}/suspend",
    response_model=(
        TenantUserMembershipResponse
    ),
)
def suspend_tenant_user(
    tenant_id: uuid.UUID,

    membership_id: uuid.UUID,

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    _require_tenant_user_management(
        db=db,
        current_user=current_user,
        tenant_id=tenant_id,
    )


    try:

        return set_membership_status(
            db=db,

            tenant_id=tenant_id,

            membership_id=(
                membership_id
            ),

            actor_user_id=(
                current_user.id
            ),

            new_status="suspended",
        )


    except TenantUserServiceError as error:

        db.rollback()

        _raise_service_error(
            error
        )


# ============================================================
# ACTIVATE MEMBERSHIP
# ============================================================


@router.post(
    "/{tenant_id}/memberships/"
    "{membership_id}/activate",
    response_model=(
        TenantUserMembershipResponse
    ),
)
def activate_tenant_user(
    tenant_id: uuid.UUID,

    membership_id: uuid.UUID,

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    _require_tenant_user_management(
        db=db,
        current_user=current_user,
        tenant_id=tenant_id,
    )


    try:

        return set_membership_status(
            db=db,

            tenant_id=tenant_id,

            membership_id=(
                membership_id
            ),

            actor_user_id=(
                current_user.id
            ),

            new_status="active",
        )


    except TenantUserServiceError as error:

        db.rollback()

        _raise_service_error(
            error
        )


# ============================================================
# REVOKE MEMBERSHIP
# ============================================================


@router.post(
    "/{tenant_id}/memberships/"
    "{membership_id}/revoke",
    response_model=(
        TenantUserMembershipResponse
    ),
)
def revoke_tenant_user(
    tenant_id: uuid.UUID,

    membership_id: uuid.UUID,

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    _require_tenant_user_management(
        db=db,
        current_user=current_user,
        tenant_id=tenant_id,
    )


    try:

        return set_membership_status(
            db=db,

            tenant_id=tenant_id,

            membership_id=(
                membership_id
            ),

            actor_user_id=(
                current_user.id
            ),

            new_status="revoked",
        )


    except TenantUserServiceError as error:

        db.rollback()

        _raise_service_error(
            error
        )