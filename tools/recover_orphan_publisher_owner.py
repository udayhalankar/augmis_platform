"""AUGMIS controlled recovery of an active publisher with no active owner.

Run from repository root:
    python -m tools.recover_orphan_publisher_owner \
       --publisher-id <UUID> --actor-email <email> --owner-email <email>

Without --apply this is a read-only preflight. For mutation add --apply and
--confirm-publisher-id <same UUID>. The publisher row is locked during mutation.
This is NOT a shortcut for ordinary publisher owner role administration.
"""
from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.db.session import SessionLocal
from services.api.app.models.iam import (
    PublisherMembership, PublisherMembershipRole, Role, User,
)
from services.api.app.models.platform import Publisher
from services.api.app.services.auth_service import normalize_email
from services.api.app.services.authorization_service import (
    AuthorizationError, require_platform_permission,
)
from services.api.app.services.audit_service import record_audit_event

ACTION = "platform.publisher.owner.recover"


class RecoveryError(Exception):
    pass


def _user(db: Session, email: str, label: str) -> User:
    user = db.scalar(select(User).where(User.email_normalized == normalize_email(email)))
    if user is None:
        raise RecoveryError(f"{label} does not exist: {email}")
    if user.status != "active":
        raise RecoveryError(f"{label} must be an active AUGMIS user: {email}")
    return user


def _has_active_owner(db: Session, publisher_id: uuid.UUID) -> bool:
    membership_id = db.scalar(
        select(PublisherMembership.id)
        .join(User, User.id == PublisherMembership.user_id)
        .join(
            PublisherMembershipRole,
            PublisherMembershipRole.membership_id == PublisherMembership.id,
        )
        .join(Role, Role.id == PublisherMembershipRole.role_id)
        .where(
            PublisherMembership.publisher_id == publisher_id,
            PublisherMembership.status == "active",
            User.status == "active",
            Role.scope_type == "publisher",
            Role.code == "publisher_owner",
        )
        .limit(1)
    )
    return membership_id is not None


def _recover(db: Session, *, publisher_id: uuid.UUID, actor_email: str,
             owner_email: str, apply: bool) -> str:
    actor = _user(db, actor_email, "Actor")
    try:
        require_platform_permission(
            db=db, user=actor, permission_code="platform.rbac.manage"
        )
    except AuthorizationError as exc:
        raise RecoveryError("Actor is not authorized: platform.rbac.manage required") from exc

    statement = select(Publisher).where(Publisher.id == publisher_id)
    if apply:
        statement = statement.with_for_update()
    publisher = db.scalar(statement)
    if publisher is None:
        raise RecoveryError("Publisher does not exist")
    if publisher.status != "active":
        raise RecoveryError("Publisher must have active status")
    if _has_active_owner(db, publisher.id):
        raise RecoveryError("Publisher already has an active Publisher Owner. Use normal administration")

    target = _user(db, owner_email, "Target owner")
    owner_role = db.scalar(
        select(Role).where(Role.scope_type == "publisher", Role.code == "publisher_owner")
    )
    if owner_role is None:
        raise RecoveryError("publisher_owner role missing; run RBAC seed first")

    membership = db.scalar(
        select(PublisherMembership).where(
            PublisherMembership.publisher_id == publisher.id,
            PublisherMembership.user_id == target.id,
        )
    )
    old_status = membership.status if membership is not None else None
    existing_codes: list[str] = []
    if membership is not None:
        existing_codes = list(db.scalars(
            select(Role.code)
            .join(PublisherMembershipRole, PublisherMembershipRole.role_id == Role.id)
            .where(PublisherMembershipRole.membership_id == membership.id)
        ))

    action = "create" if membership is None else (
        "activate" if membership.status != "active" else "augment"
    )
    message = (
        f"publisher={publisher.name} ({publisher.id}); owner={target.email}; "
        f"membership={action}; previous_status={old_status}; "
        f"existing_roles={existing_codes}"
    )
    if not apply:
        return "[DRY RUN] Eligible for controlled orphan-owner recovery: " + message

    if membership is None:
        membership = PublisherMembership(
            publisher_id=publisher.id,
            user_id=target.id,
            status="active",
        )
        db.add(membership)
        db.flush()
    elif membership.status != "active":
        membership.status = "active"
        db.flush()

    if "publisher_owner" not in existing_codes:
        db.add(PublisherMembershipRole(
            membership_id=membership.id,
            role_id=owner_role.id,
        ))
        db.flush()

    record_audit_event(
        db,
        action=ACTION,
        resource_type="publisher_membership",
        resource_id=membership.id,
        actor_user_id=actor.id,
        publisher_id=publisher.id,
        outcome="success",
        message="Platform recovered missing Publisher Owner for orphan publisher.",
        metadata={
            "publisherId": str(publisher.id),
            "publisherName": publisher.name,
            "targetUserId": str(target.id),
            "targetEmail": target.email,
            "previousMembershipStatus": old_status,
            "previousRoleCodes": existing_codes,
            "roleCodesAdded": ([] if "publisher_owner" in existing_codes
                               else ["publisher_owner"]),
        },
    )
    # Caller commits the membership change and audit row in one transaction.
    return "[APPLIED] " + message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publisher-id", type=uuid.UUID, required=True)
    parser.add_argument("--actor-email", required=True)
    parser.add_argument("--owner-email", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-publisher-id", type=uuid.UUID)
    options = parser.parse_args(argv)

    if options.apply and options.confirm_publisher_id != options.publisher_id:
        parser.error("--apply requires --confirm-publisher-id equal to --publisher-id")
    try:
        with SessionLocal() as db:
            with db.begin():
                result = _recover(
                    db,
                    publisher_id=options.publisher_id,
                    actor_email=options.actor_email,
                    owner_email=options.owner_email,
                    apply=options.apply,
                )
            print(result)
        return 0
    except (RecoveryError, ValueError) as exc:
        print("[BLOCKED]", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
