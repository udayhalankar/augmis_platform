# services/api/app/services/audit_service.py
import uuid

from sqlalchemy.orm import Session

from services.api.app.models.audit import (
    AuditEvent,
)


VALID_OUTCOMES = {
    "success",
    "denied",
    "failed",
}


class AuditError(Exception):
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