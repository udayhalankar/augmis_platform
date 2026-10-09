"""Publisher membership changes, protected ownership, and audit trail.

Mutations lock the publisher row to serialize concurrent owner changes. All
membership + audit writes share one transaction. Routes must handle rollback.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from services.api.app.models.iam import (
    PublisherMembership,
    PublisherMembershipRole,
    Role,
    User,
)
from services.api.app.models.platform import Publisher
from services.api.app.services.auth_service import normalize_email
from services.api.app.services.authorization_service import (
    AuthorizationError,
    require_publisher_permission,
)
from services.api.app.services.audit_service import record_audit_event


OWNER_CODE = "publisher_owner"
VALID_STATUSES = {"active", "suspended", "revoked"}


class PublisherUserServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _publisher(db: Session, publisher_id: uuid.UUID, *, lock: bool = False) -> Publisher:
    statement = select(Publisher).where(Publisher.id == publisher_id)
    if lock:
        statement = statement.with_for_update()
    publisher = db.scalar(statement)
    if publisher is None:
        raise PublisherUserServiceError("Publisher not found.", 404)
    return publisher


def _roles(db: Session, membership_id: uuid.UUID) -> list[Role]:
    return list(db.scalars(
        select(Role)
        .join(PublisherMembershipRole, PublisherMembershipRole.role_id == Role.id)
        .where(PublisherMembershipRole.membership_id == membership_id,
               Role.scope_type == "publisher")
        .order_by(Role.name)
    ))


def _role_codes(db: Session, membership_id: uuid.UUID) -> list[str]:
    return [r.code for r in _roles(db, membership_id)]


def _payload(db: Session, membership: PublisherMembership, user: User) -> dict:
    return {
        "membershipId": membership.id,
        "status": membership.status,
        "createdAt": membership.created_at,
        "user": {
            "id": user.id,
            "email": user.email,
            "firstName": user.first_name,
            "lastName": user.last_name,
            "status": user.status,
        },
        "roles": [
            {"id": role.id, "code": role.code, "name": role.name}
            for role in _roles(db, membership.id)
        ],
    }


def list_publisher_roles(db: Session, publisher_id: uuid.UUID) -> list[dict]:
    _publisher(db, publisher_id)
    return [{"id": r.id, "code": r.code, "name": r.name}
            for r in db.scalars(select(Role).where(Role.scope_type == "publisher")
                                .order_by(Role.name))]


def list_publisher_users(db: Session, publisher_id: uuid.UUID) -> list[dict]:
    _publisher(db, publisher_id)
    rows = db.execute(
        select(PublisherMembership, User)
        .join(User, User.id == PublisherMembership.user_id)
        .where(PublisherMembership.publisher_id == publisher_id)
        .order_by(User.email_normalized)
    ).all()
    return [_payload(db, membership, user) for membership, user in rows]


def _lock_and_authorize(db: Session, publisher_id: uuid.UUID,
                        actor_user_id: uuid.UUID) -> tuple[Publisher, bool]:
    # Serialize owner changes across all requests to this publisher.
    publisher = _publisher(db, publisher_id, lock=True)
    if publisher.status != "active":
        raise PublisherUserServiceError("Publisher is not active.", 409)
    actor = db.get(User, actor_user_id)
    if actor is None or actor.status != "active":
        raise PublisherUserServiceError("Actor account is not active.", 403)
    try:
        membership = require_publisher_permission(
            db=db, user=actor, publisher_id=publisher_id,
            permission_code="publisher.manage",
        )
    except AuthorizationError as exc:
        raise PublisherUserServiceError(str(exc), 403) from exc
    return publisher, OWNER_CODE in _role_codes(db, membership.id)


def _resolved_roles(db: Session, requested: list[str]) -> list[Role]:
    codes = list(dict.fromkeys(str(x).strip() for x in requested if str(x).strip()))
    if not codes:
        raise PublisherUserServiceError("At least one publisher role is required.")
    found = list(db.scalars(
        select(Role).where(Role.scope_type == "publisher", Role.code.in_(codes))
    ))
    role_map = {role.code: role for role in found}
    missing = [code for code in codes if code not in role_map]
    if missing:
        raise PublisherUserServiceError("Invalid publisher role: " + ", ".join(missing))
    return [role_map[code] for code in codes]


def _target(db: Session, publisher_id: uuid.UUID,
            membership_id: uuid.UUID) -> tuple[PublisherMembership, User]:
    membership = db.scalar(select(PublisherMembership).where(
        PublisherMembership.id == membership_id,
        PublisherMembership.publisher_id == publisher_id,
    ))
    if membership is None:
        raise PublisherUserServiceError("Publisher membership not found.", 404)
    user = db.get(User, membership.user_id)
    if user is None:
        raise PublisherUserServiceError("Member account not found.", 409)
    return membership, user


def _count_active_owners(db: Session, publisher_id: uuid.UUID) -> int:
    # Count distinct owners whose membership AND underlying account are active.
    memberships = db.scalars(
        select(PublisherMembership)
        .join(User, User.id == PublisherMembership.user_id)
        .join(PublisherMembershipRole,
              PublisherMembershipRole.membership_id == PublisherMembership.id)
        .join(Role, Role.id == PublisherMembershipRole.role_id)
        .where(PublisherMembership.publisher_id == publisher_id,
               PublisherMembership.status == "active",
               User.status == "active",
               Role.scope_type == "publisher",
               Role.code == OWNER_CODE)
        .distinct()
    ).all()
    return len(memberships)


def _guard_owner_change(db: Session, *, publisher_id: uuid.UUID,
                        actor_user_id: uuid.UUID,
                        membership: PublisherMembership,
                        old_codes: list[str], new_codes: list[str],
                        actor_is_owner: bool, new_status: str | None = None) -> None:
    protected_before = OWNER_CODE in old_codes
    protected_after = OWNER_CODE in new_codes
    if (protected_before or protected_after) and not actor_is_owner:
        raise PublisherUserServiceError(
            "Only an active Publisher Owner can manage protected Publisher Owner access.", 403)
    changing = (set(old_codes) != set(new_codes) or
                (new_status is not None and new_status != membership.status))
    if membership.user_id == actor_user_id and changing:
        raise PublisherUserServiceError("You cannot change your own publisher membership.", 409)
    removes_active_owner = (
        membership.status == "active" and protected_before and
        (not protected_after or (new_status is not None and new_status != "active"))
    )
    if removes_active_owner and _count_active_owners(db, publisher_id) <= 1:
        raise PublisherUserServiceError("Cannot remove the last active Publisher Owner.", 409)


def add_publisher_user(db: Session, *, publisher_id: uuid.UUID,
                       actor_user_id: uuid.UUID, email: str,
                       role_codes: list[str]) -> dict:
    _, actor_is_owner = _lock_and_authorize(db, publisher_id, actor_user_id)
    roles = _resolved_roles(db, role_codes)
    if OWNER_CODE in {role.code for role in roles} and not actor_is_owner:
        raise PublisherUserServiceError("Only a Publisher Owner can grant Publisher Owner.", 403)
    user = db.scalar(select(User).where(User.email_normalized == normalize_email(email)))
    if user is None:
        raise PublisherUserServiceError("No existing AUGMIS user has that email.", 404)
    if user.status != "active":
        raise PublisherUserServiceError("The AUGMIS user account is not active.", 409)
    existing = db.scalar(select(PublisherMembership).where(
        PublisherMembership.publisher_id == publisher_id,
        PublisherMembership.user_id == user.id,
    ))
    if existing:
        raise PublisherUserServiceError(
            f"User already has publisher membership ({existing.status}). Use its lifecycle actions.", 409)
    membership = PublisherMembership(publisher_id=publisher_id,
                                     user_id=user.id, status="active")
    db.add(membership)
    db.flush()
    for role in roles:
        db.add(PublisherMembershipRole(membership_id=membership.id, role_id=role.id))
    db.flush()
    record_audit_event(db, action="publisher.user.added",
        resource_type="publisher_membership", resource_id=membership.id,
        publisher_id=publisher_id, actor_user_id=actor_user_id,
        message=f"Publisher member added: {user.email}.",
        metadata={"targetUserId": str(user.id), "targetEmail": user.email,
                  "roleCodes": [r.code for r in roles]})
    db.commit()
    db.refresh(membership)
    return _payload(db, membership, user)


def update_publisher_roles(db: Session, *, publisher_id: uuid.UUID,
                           actor_user_id: uuid.UUID, membership_id: uuid.UUID,
                           role_codes: list[str]) -> dict:
    _, actor_is_owner = _lock_and_authorize(db, publisher_id, actor_user_id)
    membership, user = _target(db, publisher_id, membership_id)
    old_codes = _role_codes(db, membership.id)
    roles = _resolved_roles(db, role_codes)
    new_codes = [r.code for r in roles]
    _guard_owner_change(db, publisher_id=publisher_id,
        actor_user_id=actor_user_id, membership=membership,
        old_codes=old_codes, new_codes=new_codes, actor_is_owner=actor_is_owner)
    if set(old_codes) == set(new_codes):
        return _payload(db, membership, user)
    db.execute(delete(PublisherMembershipRole).where(
        PublisherMembershipRole.membership_id == membership.id))
    db.flush()
    for role in roles:
        db.add(PublisherMembershipRole(membership_id=membership.id, role_id=role.id))
    db.flush()
    record_audit_event(db, action="publisher.user.roles.updated",
        resource_type="publisher_membership", resource_id=membership.id,
        publisher_id=publisher_id, actor_user_id=actor_user_id,
        message=f"Publisher roles updated for {user.email}.",
        metadata={"targetUserId": str(user.id), "targetEmail": user.email,
                  "previousRoleCodes": old_codes, "roleCodes": new_codes})
    db.commit()
    db.refresh(membership)
    return _payload(db, membership, user)


def change_publisher_status(db: Session, *, publisher_id: uuid.UUID,
                            actor_user_id: uuid.UUID, membership_id: uuid.UUID,
                            status: str) -> dict:
    if status not in VALID_STATUSES:
        raise PublisherUserServiceError("Invalid publisher membership status.")
    _, actor_is_owner = _lock_and_authorize(db, publisher_id, actor_user_id)
    membership, user = _target(db, publisher_id, membership_id)
    old_codes = _role_codes(db, membership.id)
    _guard_owner_change(db, publisher_id=publisher_id,
        actor_user_id=actor_user_id, membership=membership,
        old_codes=old_codes, new_codes=old_codes, actor_is_owner=actor_is_owner,
        new_status=status)
    if membership.status == status:
        return _payload(db, membership, user)
    if status == "active" and user.status != "active":
        raise PublisherUserServiceError("The AUGMIS user account is not active.", 409)
    before = membership.status
    membership.status = status
    db.flush()
    action = {"active": "publisher.user.activated",
              "suspended": "publisher.user.suspended",
              "revoked": "publisher.user.revoked"}[status]
    record_audit_event(db, action=action,
        resource_type="publisher_membership", resource_id=membership.id,
        publisher_id=publisher_id, actor_user_id=actor_user_id,
        message=f"Publisher member {status}: {user.email}.",
        metadata={"targetUserId": str(user.id), "targetEmail": user.email,
                  "previousStatus": before, "status": status,
                  "roleCodes": old_codes})
    db.commit()
    db.refresh(membership)
    return _payload(db, membership, user)
