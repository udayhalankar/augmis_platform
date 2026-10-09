import uuid

from datetime import datetime

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

from services.api.app.models.platform import (
    Tenant,
)

from services.api.app.services.audit_service import (
    AuditQueryError,
    audit_event_payload,
    get_audit_filter_options,
    query_audit_events,
)

from services.api.app.services.authorization_service import (
    AuthorizationError,
    require_platform_permission,
    require_tenant_permission,
)


router = APIRouter(
    prefix="/api/v1",
    tags=["Audit"],
)


# ============================================================
# AUTHORIZATION HELPERS
# ============================================================


def _require_tenant_audit_access(
    *,
    db: Session,
    current_user: User,
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

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=tenant.id,
            permission_code="audit.view",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    return tenant


def _require_platform_audit_access(
    *,
    db: Session,
    current_user: User,
) -> None:

    try:

        require_platform_permission(
            db=db,
            user=current_user,
            permission_code=(
                "platform.audit.view"
            ),
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error


def _run_query(
    *,
    db: Session,

    tenant_scope_id:
        uuid.UUID | None = None,

    tenant_id:
        uuid.UUID | None = None,

    publisher_id:
        uuid.UUID | None = None,

    action:
        str | None = None,

    action_prefix:
        str | None = None,

    category:
        str | None = None,

    outcome:
        str | None = None,

    resource_type:
        str | None = None,

    resource_id:
        str | None = None,

    actor_user_id:
        uuid.UUID | None = None,

    from_date:
        datetime | None = None,

    to_date:
        datetime | None = None,

    search:
        str | None = None,

    limit: int = 100,

    offset: int = 0,
):

    try:

        return query_audit_events(
            db=db,
            tenant_scope_id=(
                tenant_scope_id
            ),
            tenant_id=tenant_id,
            publisher_id=publisher_id,
            action=action,
            action_prefix=(
                action_prefix
            ),
            category=category,
            outcome=outcome,
            resource_type=(
                resource_type
            ),
            resource_id=resource_id,
            actor_user_id=(
                actor_user_id
            ),
            from_date=from_date,
            to_date=to_date,
            search=search,
            limit=limit,
            offset=offset,
        )

    except AuditQueryError as error:

        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error


# ============================================================
# PERSONAL AUDIT EVENTS
#
# Every authenticated user may see THEIR OWN audit events.
# No audit.view permission is required here because the actor
# scope is enforced server-side and cannot be overridden by
# a client-supplied actor_user_id.
# ============================================================


@router.get(
    "/audit-events/me",
)
def list_my_audit_events(
    tenant_id:
        uuid.UUID | None = None,

    publisher_id:
        uuid.UUID | None = None,

    action:
        str | None = None,

    action_prefix:
        str | None = None,

    category:
        str | None = None,

    outcome:
        str | None = None,

    resource_type:
        str | None = None,

    resource_id:
        str | None = None,

    search:
        str | None = None,

    from_date:
        datetime | None = Query(
            default=None,
            alias="from",
        ),

    to_date:
        datetime | None = Query(
            default=None,
            alias="to",
        ),

    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),

    offset: int = Query(
        default=0,
        ge=0,
    ),

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    total, events = _run_query(
        db=db,
        tenant_id=tenant_id,
        publisher_id=publisher_id,
        action=action,
        action_prefix=action_prefix,
        category=category,
        outcome=outcome,
        resource_type=resource_type,
        resource_id=resource_id,

        # SECURITY BOUNDARY:
        # Never accept actor_user_id from the request.
        # The authenticated user is always forced here.
        actor_user_id=current_user.id,

        from_date=from_date,
        to_date=to_date,
        search=search,
        limit=limit,
        offset=offset,
    )

    return {
        "scope": {
            "type":
                "personal",
        },

        "pagination": {
            "total":
                total,

            "limit":
                limit,

            "offset":
                offset,

            "returned":
                len(events),
        },

        "items": [
            audit_event_payload(
                event
            )
            for event in events
        ],
    }


# ============================================================
# PERSONAL FILTER OPTIONS
#
# The existing catalogue service remains the source for the
# non-identity filter vocabulary. Identity-bearing collections
# are deliberately restricted so this endpoint cannot expose
# other users, tenants or publishers to a standard user.
# ============================================================


@router.get(
    "/audit-events/me/filter-options",
)
def my_audit_filter_options(
    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    options = get_audit_filter_options(
        db=db,
    )

    return {
        "categories":
            options.get(
                "categories",
                [],
            ),

        "actions":
            options.get(
                "actions",
                [],
            ),

        "outcomes":
            options.get(
                "outcomes",
                [],
            ),

        "resourceTypes":
            options.get(
                "resourceTypes",
                [],
            ),

        # Only the signed-in user is exposed.
        "actors": [
            {
                "id":
                    str(current_user.id),

                "email":
                    current_user.email,

                "firstName":
                    current_user.first_name,

                "lastName":
                    current_user.last_name,
            }
        ],

        # Personal scope does not expose the global
        # tenant/publisher directory through filter options.
        "tenants": [],
        "publishers": [],
    }


# ============================================================
# TENANT AUDIT EVENTS
# ============================================================


@router.get(
    "/audit-events",
)
def list_audit_events(
    tenant_id: uuid.UUID,

    publisher_id:
        uuid.UUID | None = None,

    action:
        str | None = None,

    action_prefix:
        str | None = None,

    category:
        str | None = None,

    outcome:
        str | None = None,

    resource_type:
        str | None = None,

    resource_id:
        str | None = None,

    actor_user_id:
        uuid.UUID | None = None,

    search:
        str | None = None,

    from_date:
        datetime | None = Query(
            default=None,
            alias="from",
        ),

    to_date:
        datetime | None = Query(
            default=None,
            alias="to",
        ),

    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),

    offset: int = Query(
        default=0,
        ge=0,
    ),

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    tenant = (
        _require_tenant_audit_access(
            db=db,
            current_user=current_user,
            tenant_id=tenant_id,
        )
    )

    total, events = _run_query(
        db=db,
        tenant_scope_id=tenant.id,
        publisher_id=publisher_id,
        action=action,
        action_prefix=action_prefix,
        category=category,
        outcome=outcome,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
        from_date=from_date,
        to_date=to_date,
        search=search,
        limit=limit,
        offset=offset,
    )

    return {
        "scope": {
            "type":
                "tenant",

            "tenantId":
                str(tenant.id),

            "tenantName":
                tenant.name,
        },

        # Preserve the existing tenant payload
        # for compatibility with current callers.
        "tenant": {
            "id":
                str(tenant.id),

            "name":
                tenant.name,
        },

        "pagination": {
            "total":
                total,

            "limit":
                limit,

            "offset":
                offset,

            "returned":
                len(events),
        },

        "items": [
            audit_event_payload(
                event
            )
            for event in events
        ],
    }


# ============================================================
# TENANT FILTER OPTIONS
# ============================================================


@router.get(
    "/audit-events/filter-options",
)
def tenant_audit_filter_options(
    tenant_id: uuid.UUID,

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    tenant = (
        _require_tenant_audit_access(
            db=db,
            current_user=current_user,
            tenant_id=tenant_id,
        )
    )

    return get_audit_filter_options(
        db=db,
        tenant_scope_id=tenant.id,
    )


# ============================================================
# PLATFORM AUDIT EVENTS
# ============================================================


@router.get(
    "/platform/audit-events",
)
def list_platform_audit_events(
    tenant_id:
        uuid.UUID | None = None,

    publisher_id:
        uuid.UUID | None = None,

    action:
        str | None = None,

    action_prefix:
        str | None = None,

    category:
        str | None = None,

    outcome:
        str | None = None,

    resource_type:
        str | None = None,

    resource_id:
        str | None = None,

    actor_user_id:
        uuid.UUID | None = None,

    search:
        str | None = None,

    from_date:
        datetime | None = Query(
            default=None,
            alias="from",
        ),

    to_date:
        datetime | None = Query(
            default=None,
            alias="to",
        ),

    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),

    offset: int = Query(
        default=0,
        ge=0,
    ),

    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    _require_platform_audit_access(
        db=db,
        current_user=current_user,
    )

    total, events = _run_query(
        db=db,
        tenant_id=tenant_id,
        publisher_id=publisher_id,
        action=action,
        action_prefix=action_prefix,
        category=category,
        outcome=outcome,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
        from_date=from_date,
        to_date=to_date,
        search=search,
        limit=limit,
        offset=offset,
    )

    return {
        "scope": {
            "type":
                "platform",
        },

        "pagination": {
            "total":
                total,

            "limit":
                limit,

            "offset":
                offset,

            "returned":
                len(events),
        },

        "items": [
            audit_event_payload(
                event
            )
            for event in events
        ],
    }


# ============================================================
# PLATFORM FILTER OPTIONS
# ============================================================


@router.get(
    "/platform/audit-events/filter-options",
)
def platform_audit_filter_options(
    db: Session = Depends(
        get_db
    ),

    current_user: User = Depends(
        get_current_user
    ),
):

    _require_platform_audit_access(
        db=db,
        current_user=current_user,
    )

    return get_audit_filter_options(
        db=db,
    )