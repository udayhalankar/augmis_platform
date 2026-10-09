# services/api/app/services/audit_service.py
import uuid

from datetime import datetime

from sqlalchemy import (
    Text,
    and_,
    cast,
    func,
    or_,
    select,
)

from sqlalchemy.orm import Session

from services.api.app.models.audit import (
    AuditEvent,
)

from services.api.app.models.iam import (
    User,
)

from services.api.app.models.platform import (
    Publisher,
    Tenant,
)


VALID_OUTCOMES = {
    "success",
    "denied",
    "failed",
}

RUNTIME_AUDIT_ACTIONS = {
    "application.deploy",
    "application.upgrade",
    "application.rollback",
    "application.stop",
    "application.restart",
}


AUDIT_CATEGORY_LABELS = {
    "authentication":
        "Authentication",

    "iam":
        "IAM & RBAC",

    "tenant":
        "Tenant",

    "publisher":
        "Publisher",

    "application":
        "Application",

    "runtime":
        "Runtime",

    "offer":
        "Offer",

    "subscription":
        "Subscription",

    "configuration":
        "Configuration",

    "delivery":
        "Delivery",
}


VALID_AUDIT_CATEGORIES = set(
    AUDIT_CATEGORY_LABELS
)


class AuditError(Exception):
    pass

class AuditQueryError(Exception):
    pass

def record_audit_event(
    db: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: str | uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    publisher_id: uuid.UUID | None = None,
    outcome: str = "success",
    message: str | None = None,
    metadata: dict | None = None,
    request_id: str | None = None,
) -> AuditEvent:

    if outcome not in VALID_OUTCOMES:

        raise AuditError(
            f"Invalid audit outcome: {outcome}"
        )

    if not action.strip():

        raise AuditError(
            "Audit action is required."
        )

    if not resource_type.strip():

        raise AuditError(
            "Audit resource type is required."
        )

    event = AuditEvent(
        actor_user_id=actor_user_id,
        tenant_id=tenant_id,
        publisher_id=publisher_id,

        action=action.strip(),

        resource_type=(
            resource_type.strip()
        ),

        resource_id=(
            str(resource_id)
            if resource_id is not None
            else None
        ),

        outcome=outcome,

        message=message,

        metadata_json=(
            metadata or {}
        ),

        request_id=request_id,
    )

    db.add(event)

    # Deliberately flush, but DO NOT commit.
    #
    # The calling business operation controls the
    # transaction so successful action + audit event
    # can commit together.

    db.flush()

    return event

# ============================================================
# AUDIT QUERY HELPERS
# ============================================================


def _escaped_search_pattern(
    value: str,
) -> str:

    escaped = (
        value
        .replace(
            "\\",
            "\\\\",
        )
        .replace(
            "%",
            "\\%",
        )
        .replace(
            "_",
            "\\_",
        )
    )

    return f"%{escaped}%"


def _category_condition(
    category: str,
):

    normalized = (
        category
        .strip()
        .lower()
    )

    if (
        normalized
        not in VALID_AUDIT_CATEGORIES
    ):

        raise AuditQueryError(
            (
                "Invalid audit category: "
                f"{category}"
            )
        )

    if normalized == "authentication":

        return (
            AuditEvent.action.like(
                "auth.%"
            )
        )

    if normalized == "iam":

        return or_(
            AuditEvent.action.like(
                "platform.rbac.%"
            ),

            AuditEvent.action.like(
                "tenant.user.%"
            ),

            AuditEvent.action.like(
                "tenant.invitation.%"
            ),
        )

    if normalized == "tenant":

        return or_(
            AuditEvent.action.like(
                "platform.tenant.%"
            ),

            AuditEvent.action.like(
                "tenant.lifecycle.%"
            ),
        )

    if normalized == "publisher":

        return or_(
            AuditEvent.action.like(
                "platform.publisher.%"
            ),

            AuditEvent.action.like(
                "publisher.%"
            ),
        )

    if normalized == "runtime":

        return AuditEvent.action.in_(
            RUNTIME_AUDIT_ACTIONS
        )

    if normalized == "application":

        return and_(
            AuditEvent.action.like(
                "application.%"
            ),

            ~AuditEvent.action.in_(
                RUNTIME_AUDIT_ACTIONS
            ),
        )

    if normalized == "offer":

        return (
            AuditEvent.action.like(
                "offer.%"
            )
        )

    if normalized == "subscription":

        return (
            AuditEvent.action.like(
                "subscription.%"
            )
        )

    if normalized == "configuration":

        return (
            AuditEvent.action.like(
                "platform.settings.%"
            )
        )

    return or_(
        AuditEvent.action.like(
            "email.%"
        ),

        AuditEvent.action.like(
            "tenant.invitation.email.%"
        ),
    )


def build_audit_conditions(
    *,
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
):

    if (
        from_date
        and to_date
        and from_date > to_date
    ):

        raise AuditQueryError(
            (
                "'from' must be earlier "
                "than or equal to 'to'."
            )
        )

    if (
        outcome
        and outcome not in VALID_OUTCOMES
    ):

        raise AuditQueryError(
            (
                "Invalid audit outcome: "
                f"{outcome}"
            )
        )

    conditions = []

    # --------------------------------------------------------
    # TENANT SECURITY BOUNDARY
    #
    # tenant_scope_id is authoritative and cannot be
    # overridden by a request filter.
    # --------------------------------------------------------

    if tenant_scope_id is not None:

        conditions.append(
            AuditEvent.tenant_id
            == tenant_scope_id
        )

    elif tenant_id is not None:

        conditions.append(
            AuditEvent.tenant_id
            == tenant_id
        )

    if publisher_id is not None:

        conditions.append(
            AuditEvent.publisher_id
            == publisher_id
        )

    if action:

        conditions.append(
            AuditEvent.action
            == action.strip()
        )

    if action_prefix:

        conditions.append(
            AuditEvent.action.startswith(
                action_prefix.strip(),
                autoescape=True,
            )
        )

    if category:

        conditions.append(
            _category_condition(
                category
            )
        )

    if outcome:

        conditions.append(
            AuditEvent.outcome
            == outcome
        )

    if resource_type:

        conditions.append(
            AuditEvent.resource_type
            == resource_type.strip()
        )

    if resource_id:

        conditions.append(
            AuditEvent.resource_id
            == resource_id.strip()
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

    if (
        search
        and search.strip()
    ):

        pattern = (
            _escaped_search_pattern(
                search.strip()
            )
        )

        conditions.append(
            or_(
                AuditEvent.action.ilike(
                    pattern,
                    escape="\\",
                ),

                AuditEvent.resource_type.ilike(
                    pattern,
                    escape="\\",
                ),

                AuditEvent.resource_id.ilike(
                    pattern,
                    escape="\\",
                ),

                AuditEvent.message.ilike(
                    pattern,
                    escape="\\",
                ),

                cast(
                    AuditEvent.metadata_json,
                    Text,
                ).ilike(
                    pattern,
                    escape="\\",
                ),
            )
        )

    return conditions


def query_audit_events(
    db: Session,
    *,
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

    conditions = build_audit_conditions(
        tenant_scope_id=tenant_scope_id,
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
    )

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

    events = list(
        db.scalars(
            select(
                AuditEvent
            )
            .where(
                *conditions
            )
            .order_by(
                AuditEvent.created_at.desc(),
                AuditEvent.id.desc(),
            )
            .offset(
                offset
            )
            .limit(
                limit
            )
        )
    )

    return (
        total,
        events,
    )


def audit_event_payload(
    event: AuditEvent,
) -> dict:

    return {
        "id":
            str(event.id),

        "createdAt":
            event.created_at,

        "actorUserId": (
            str(event.actor_user_id)
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


def get_audit_filter_options(
    db: Session,
    *,
    tenant_scope_id:
        uuid.UUID | None = None,
) -> dict:

    conditions = []

    if tenant_scope_id is not None:

        conditions.append(
            AuditEvent.tenant_id
            == tenant_scope_id
        )

    actions = list(
        db.scalars(
            select(
                AuditEvent.action
            )
            .where(
                *conditions
            )
            .distinct()
            .order_by(
                AuditEvent.action
            )
        )
    )

    outcomes = list(
        db.scalars(
            select(
                AuditEvent.outcome
            )
            .where(
                *conditions
            )
            .distinct()
            .order_by(
                AuditEvent.outcome
            )
        )
    )

    resource_types = list(
        db.scalars(
            select(
                AuditEvent.resource_type
            )
            .where(
                *conditions
            )
            .distinct()
            .order_by(
                AuditEvent.resource_type
            )
        )
    )

    actor_ids = list(
        db.scalars(
            select(
                AuditEvent.actor_user_id
            )
            .where(
                *conditions,

                AuditEvent.actor_user_id
                .is_not(None),
            )
            .distinct()
        )
    )

    tenant_ids = list(
        db.scalars(
            select(
                AuditEvent.tenant_id
            )
            .where(
                *conditions,

                AuditEvent.tenant_id
                .is_not(None),
            )
            .distinct()
        )
    )

    publisher_ids = list(
        db.scalars(
            select(
                AuditEvent.publisher_id
            )
            .where(
                *conditions,

                AuditEvent.publisher_id
                .is_not(None),
            )
            .distinct()
        )
    )

    actors = []

    if actor_ids:

        actor_rows = list(
            db.scalars(
                select(
                    User
                )
                .where(
                    User.id.in_(
                        actor_ids
                    )
                )
                .order_by(
                    User.email
                )
            )
        )

        actors = [
            {
                "id":
                    str(user.id),

                "email":
                    user.email,

                "firstName":
                    user.first_name,

                "lastName":
                    user.last_name,
            }

            for user in actor_rows
        ]

    tenants = []

    if tenant_ids:

        tenant_rows = list(
            db.scalars(
                select(
                    Tenant
                )
                .where(
                    Tenant.id.in_(
                        tenant_ids
                    )
                )
                .order_by(
                    Tenant.name
                )
            )
        )

        tenants = [
            {
                "id":
                    str(tenant.id),

                "name":
                    tenant.name,

                "slug":
                    tenant.slug,
            }

            for tenant in tenant_rows
        ]

    publishers = []

    if publisher_ids:

        publisher_rows = list(
            db.scalars(
                select(
                    Publisher
                )
                .where(
                    Publisher.id.in_(
                        publisher_ids
                    )
                )
                .order_by(
                    Publisher.name
                )
            )
        )

        publishers = [
            {
                "id":
                    str(publisher.id),

                "name":
                    publisher.name,

                "slug":
                    publisher.slug,
            }

            for publisher in publisher_rows
        ]

    return {
        "categories": [
            {
                "key":
                    key,

                "label":
                    label,
            }

            for (
                key,
                label,
            ) in (
                AUDIT_CATEGORY_LABELS
                .items()
            )
        ],

        "actions":
            actions,

        "outcomes":
            outcomes,

        "resourceTypes":
            resource_types,

        "actors":
            actors,

        "tenants":
            tenants,

        "publishers":
            publishers,
    }