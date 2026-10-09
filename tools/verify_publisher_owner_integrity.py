"""Read-only guard against active publisher workspaces without an active owner.
Run: python -m tools.verify_publisher_owner_integrity
"""
from sqlalchemy import select
from services.api.app.db.session import SessionLocal
from services.api.app.models.iam import (
    PublisherMembership, PublisherMembershipRole, Role, User,
)
from services.api.app.models.platform import Publisher


def main() -> None:
    errors: list[str] = []
    with SessionLocal() as db:
        for publisher in db.scalars(select(Publisher).where(Publisher.status == "active")):
            active_owner = db.scalar(
                select(PublisherMembership.id)
                .join(User, User.id == PublisherMembership.user_id)
                .join(PublisherMembershipRole,
                      PublisherMembershipRole.membership_id == PublisherMembership.id)
                .join(Role, Role.id == PublisherMembershipRole.role_id)
                .where(PublisherMembership.publisher_id == publisher.id,
                       PublisherMembership.status == "active",
                       User.status == "active",
                       Role.scope_type == "publisher",
                       Role.code == "publisher_owner")
                .limit(1)
            )
            if active_owner is None:
                errors.append(f"{publisher.name} ({publisher.id}): no active Publisher Owner")
        roleless = db.execute(
            select(PublisherMembership.id)
            .outerjoin(PublisherMembershipRole,
                       PublisherMembershipRole.membership_id == PublisherMembership.id)
            .where(PublisherMembership.status == "active",
                   PublisherMembershipRole.id.is_(None))
        ).scalars().all()
        for membership_id in roleless:
            errors.append(f"Active membership {membership_id}: no publisher role")
    if errors:
        for error in errors:
            print("[FAIL]", error)
        raise SystemExit(1)
    print("[PASS] Every active publisher has an active Publisher Owner.")
    print("[PASS] Every active publisher membership has a role.")


if __name__ == "__main__":
    main()
