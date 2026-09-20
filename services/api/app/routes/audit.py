import uuid

from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)

from sqlalchemy import (
    func,
    select,
)

from sqlalchemy.orm import Session

from services.api.app.core.auth import (
    get_current_user,
)

from services.api.app.db.session import (
    get_db,
)

from services.api.app.models.audit import (
    AuditEvent,
)

from services.api.app.models.iam import (
    User,
)

from services.api.app.models.platform import (
    Tenant,
)

from services.api.app.services.authorization_service import (
    AuthorizationError,
    require_tenant_permission,
)


router = APIRouter(
    prefix="/api/v1",
    tags=["Audit"],
)


@router.get(
    "/audit-events",
)
def list_audit_events(
    tenant_id: uuid.UUID,

    action: str | None = None,

    outcome: str | None = None,

    resource_type: str | None = None,

    resource_id: str | None = None,

    actor_user_id: uuid.UUID | None = None,

    from_date: datetime | None = Query(
        default=None,
        alias="from",
    ),

    to_date: datetime | None = Query(
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

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    ),
):

    # =====================================================
    # 1. TENANT
    # =====================================================

    tenant = db.get(
        Tenant,
        tenant_id,
    )

    if not tenant:

        raise HTTPException(
            status_code=404,
            detail="Tenant not found",
        )

    # =====================================================
    # 2. RBAC
    # =====================================================

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

    # =====================================================
    # 3. BUILD FILTERS
    #
    # tenant_id is ALWAYS enforced server-side.
    # =====================================================

    conditions = [
        AuditEvent.tenant_id
        == tenant.id
    ]

    if action:

        conditions.append(
            AuditEvent.action
            == action
        )

    if outcome:

        conditions.append(
            AuditEvent.outcome
            == outcome
        )

    if resource_type:

        conditions.append(
            AuditEvent.resource_type
            == resource_type
        )

    if resource_id:

        conditions.append(
            AuditEvent.resource_id
            == resource_id
        )

    if actor_user_id:

        conditions.append(
            AuditEvent.actor_user_id
            == actor_user_id
        )

    if from_date:

        conditions.append(
            AuditEvent.created_at
            >= from_date
        )

    if to_date:

        conditions.append(
            AuditEvent.created_at
            <= to_date
        )

    # =====================================================
    # 4. TOTAL COUNT
    # =====================================================

    total = db.scalar(
        select(
            func.count(
                AuditEvent.id
            )
        )
        .where(
            *conditions
        )
    ) or 0

    # =====================================================
    # 5. EVENTS
    # =====================================================

    events = list(
        db.scalars(
            select(AuditEvent)
            .where(
                *conditions
            )
            .order_by(
                AuditEvent.created_at.desc()
            )
            .offset(
                offset
            )
            .limit(
                limit
            )
        )
    )

    # =====================================================
    # 6. RESPONSE
    # =====================================================

    return {
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
            {
                "id":
                    str(event.id),

                "createdAt":
                    event.created_at,

                "actorUserId": (
                    str(
                        event.actor_user_id
                    )
                    if event.actor_user_id
                    else None
                ),

                "tenantId": (
                    str(event.tenant_id)
                    if event.tenant_id
                    else None
                ),

                "publisherId": (
                    str(event.publisher_id)
                    if event.publisher_id
                    else None
                ),

                "action":
                    event.action,

                "resourceType":
                    event.resource_type,

                "resourceId":
                    event.resource_id,

                "outcome":
                    event.outcome,

                "message":
                    event.message,

                "metadata":
                    event.metadata_json,

                "requestId":
                    event.request_id,
            }

            for event in events
        ],
    }