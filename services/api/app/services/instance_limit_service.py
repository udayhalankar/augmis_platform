import uuid

from sqlalchemy import (
    func,
    select,
    text,
)

from sqlalchemy.orm import Session

from services.api.app.models.commerce import (
    SubscriptionEntitlement,
)

from services.api.app.models.platform import (
    ApplicationInstance,
)


class InstanceLimitError(Exception):
    pass


ACTIVE_INSTANCE_STATUSES = (
    "provisioning",
    "running",
    "upgrading",
)


def get_max_instances(
    entitlement: SubscriptionEntitlement,
) -> int | None:

    value = entitlement.value_json or {}

    max_instances = value.get(
        "maxInstances"
    )

    if max_instances is None:
        return None

    if (
        isinstance(max_instances, bool)
        or not isinstance(max_instances, int)
        or max_instances < 1
    ):
        raise InstanceLimitError(
            "Invalid maxInstances entitlement value."
        )

    return max_instances


def acquire_instance_limit_lock(
    db: Session,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
):

    lock_key = (
        f"instance-limit:"
        f"{tenant_id}:"
        f"{application_id}"
    )

    db.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended(:lock_key, 0)"
            ")"
        ),
        {
            "lock_key": lock_key
        },
    )


def require_instance_capacity(
    db: Session,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    entitlement: SubscriptionEntitlement,
):

    max_instances = get_max_instances(
        entitlement
    )

    print(
        "INSTANCE LIMIT CHECK:",
        {
            "tenant_id": str(tenant_id),
            "application_id": str(application_id),
            "entitlement_value": entitlement.value_json,
            "max_instances": max_instances,
        }
    )

    if max_instances is None:
        return

    acquire_instance_limit_lock(
        db=db,
        tenant_id=tenant_id,
        application_id=application_id,
    )

    current_count = db.scalar(
        select(
            func.count(
                ApplicationInstance.id
            )
        )
        .where(
            ApplicationInstance.tenant_id
            == tenant_id,

            ApplicationInstance.application_id
            == application_id,

            ApplicationInstance.status.in_(
                ACTIVE_INSTANCE_STATUSES
            ),
        )
    ) or 0

    print(
        "INSTANCE LIMIT COUNT:",
        {
            "current_count": current_count,
            "max_instances": max_instances,
        }
    )

    if current_count >= max_instances:

        raise InstanceLimitError(
            f"Application instance limit reached: "
            f"{current_count}/{max_instances}."
        )