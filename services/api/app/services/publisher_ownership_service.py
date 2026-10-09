"""Organization-owned publishers: explicit association, never inferred from domains.

Tenant = organization. Publisher workspace belongs to one organization.
Publisher membership is an independent authorization boundary.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.models.iam import (
    PublisherMembership,
    PublisherMembershipRole,
    Role,
    TenantMembership,
    TenantMembershipRole,
    User,
)
from services.api.app.models.platform import Publisher, Tenant
from services.api.app.services.audit_service import record_audit_event
from services.api.app.services.auth_service import normalize_email


class PublisherOwnershipError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


def get_active_organization(db: Session, tenant_id: uuid.UUID, *, lock: bool = False) -> Tenant:
    stmt = select(Tenant).where(Tenant.id == tenant_id)
    if lock:
        stmt = stmt.with_for_update()
    tenant = db.scalar(stmt)
    if tenant is None:
        raise PublisherOwnershipError("Owning organization (tenant) not found.", 404)
    if tenant.status != "active":
        raise PublisherOwnershipError("Owning organization must be active.", 409)
    return tenant


def resolve_initial_publisher_owner(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor: User,
    initial_owner_email: str | None,
) -> User:
    """Initial Publisher Owner must be an active Tenant Owner of the organization."""
    if initial_owner_email:
        candidate = db.scalar(
            select(User).where(User.email_normalized == normalize_email(initial_owner_email))
        )
    else:
        candidate = actor

    if candidate is None or candidate.status != "active":
        raise PublisherOwnershipError("Initial Publisher Owner must be an existing active user.")

    matching_id = db.scalar(
        select(TenantMembership.id)
        .join(TenantMembershipRole, TenantMembershipRole.membership_id == TenantMembership.id)
        .join(Role, Role.id == TenantMembershipRole.role_id)
        .where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == candidate.id,
            TenantMembership.status == "active",
            Role.scope_type == "tenant",
            Role.code == "tenant_owner",
        ).limit(1)
    )
    if matching_id is None:
        raise PublisherOwnershipError(
            "Initial Publisher Owner must be an active Tenant Owner of the owning "
            "organization. Provide initialOwnerEmail for an existing Tenant Owner."
        )
    return candidate


def _shared_active_owner_exists(db: Session, *, publisher_id: uuid.UUID,
                                tenant_id: uuid.UUID) -> bool:
    """Guard legacy binding: at least one Publisher Owner belongs to the organization."""
    owner_membership_id = db.scalar(
        select(PublisherMembership.id)
        .join(User, User.id == PublisherMembership.user_id)
        .join(PublisherMembershipRole,
              PublisherMembershipRole.membership_id == PublisherMembership.id)
        .join(Role, Role.id == PublisherMembershipRole.role_id)
        .join(TenantMembership, TenantMembership.user_id == User.id)
        .where(
            PublisherMembership.publisher_id == publisher_id,
            PublisherMembership.status == "active",
            User.status == "active",
            Role.scope_type == "publisher",
            Role.code == "publisher_owner",
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.status == "active",
        ).limit(1)
    )
    return owner_membership_id is not None


def assign_publisher_organization(
    db: Session, *, publisher_id: uuid.UUID, tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> Publisher:
    """Bind previously-unassigned legacy publisher, atomically with audit.

    Caller MUST enforce platform.publishers.manage first. Does not perform
    ownership transfers; those need a separate reviewed governance process.
    """
    # Lock publisher row to serialize competing ownership assignments.
    publisher = db.scalar(
        select(Publisher).where(Publisher.id == publisher_id).with_for_update()
    )
    if publisher is None:
        raise PublisherOwnershipError("Publisher not found.", 404)
    if publisher.status != "active":
        raise PublisherOwnershipError("Publisher must be active.")
    if publisher.tenant_id is not None:
        raise PublisherOwnershipError(
            "Publisher already belongs to an organization. Ownership transfer "
            "requires separate approval; assignment is not repeatable."
        )
    tenant = get_active_organization(db, tenant_id, lock=True)
    if not _shared_active_owner_exists(db, publisher_id=publisher.id, tenant_id=tenant.id):
        raise PublisherOwnershipError(
            "Cannot assign publisher: at least one active Publisher Owner must "
            "also be an active member of the target organization. Review memberships first."
        )

    publisher.tenant_id = tenant.id
    db.flush()
    record_audit_event(
        db,
        action="platform.publisher.organization.assigned",
        resource_type="publisher",
        resource_id=publisher.id,
        actor_user_id=actor_user_id,
        publisher_id=publisher.id,
        tenant_id=tenant.id,
        outcome="success",
        message="Publisher workspace assigned to an organization.",
        metadata={
            "publisherId": str(publisher.id),
            "publisherName": publisher.name,
            "previousTenantId": None,
            "tenantId": str(tenant.id),
            "tenantName": tenant.name,
        },
    )
    # Route commits assignment and audit together; no commit here.
    return publisher
