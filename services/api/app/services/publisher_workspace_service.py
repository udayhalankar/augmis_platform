"""Activate a single publisher workspace per organization.

Tenant Owner initiates activation; publisher membership remains independent.
The enclosing route owns commit/rollback, and audit is in the same transaction.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.models.iam import User
from services.api.app.models.platform import Publisher
from services.api.app.services.audit_service import record_audit_event
from services.api.app.services.membership_service import create_publisher_owner_membership
from services.api.app.services.publisher_ownership_service import (
    PublisherOwnershipError,
    get_active_organization,
    resolve_initial_publisher_owner,
)


def activate_organization_publisher(
    db: Session, *, tenant_id: uuid.UUID, actor: User,
) -> tuple[Publisher, bool]:
    """Return (publisher, newly_created), serialized on the tenant row.

    Authorization: caller MUST first enforce tenant.manage. This service ALSO
    checks actor's active tenant_owner role, because tenant_admin also has
    tenant.manage but must not bootstrap a protected publisher_owner role.
    """
    tenant = get_active_organization(db, tenant_id, lock=True)
    if actor.status != "active":
        raise PublisherOwnershipError("An active AUGMIS user is required.", 403)
    try:
        resolve_initial_publisher_owner(
            db, tenant_id=tenant.id, actor=actor, initial_owner_email=None,
        )
    except PublisherOwnershipError as exc:
        raise PublisherOwnershipError(
            "Only an active Tenant Owner can enable publisher capability.", 403
        ) from exc

    existing = db.scalar(
        select(Publisher).where(Publisher.tenant_id == tenant.id)
    )
    if existing is not None:
        if existing.status != "active":
            raise PublisherOwnershipError(
                "Organization publisher is inactive. Contact publisher administration; "
                "a second workspace cannot be created.", 409
            )
        # Do not grant publisher membership to anyone just because they hold
        # tenant_owner. An existing workspace has an independent owner.
        return existing, False

    # Name defaults to the ORGANIZATION account name, not a human user's name.
    # Deterministic globally unique slug prevents collision with legacy names.
    # This is an internal workspace key; display name is tenant.name.
    slug = f"org-{tenant.id.hex}-publisher"
    publisher = Publisher(
        tenant_id=tenant.id, name=f"{tenant.name} Workspace", slug=slug, status="active"
    )
    db.add(publisher)
    db.flush()

    create_publisher_owner_membership(
        db=db, publisher_id=publisher.id, user_id=actor.id,
    )
    record_audit_event(
        db,
        action="publisher.workspace.activated",
        resource_type="publisher",
        resource_id=publisher.id,
        tenant_id=tenant.id,
        publisher_id=publisher.id,
        actor_user_id=actor.id,
        outcome="success",
        message="Organization publisher workspace activated.",
        metadata={
            "tenantId": str(tenant.id),
            "publisherId": str(publisher.id),
            "publisherName": publisher.name,
            "initialOwnerUserId": str(actor.id),
            "source": "tenant_owner_self_service",
        },
    )
    return publisher, True
