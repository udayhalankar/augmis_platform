"""READ-ONLY organization/publisher reconciliation inventory for Step 53F.

Run from AUGMIS repo root: python -m tools.report_legacy_publisher_reconciliation
This command NEVER assigns, merges, deactivates, or deletes a publisher.
"""
from __future__ import annotations

from sqlalchemy import func, select
from services.api.app.db.session import SessionLocal
from services.api.app.models.iam import PublisherMembership, PublisherMembershipRole, Role, User
from services.api.app.models.platform import Publisher, Tenant, Application


def main() -> int:
    with SessionLocal() as db:
        publishers = list(db.scalars(select(Publisher).order_by(Publisher.name, Publisher.id)))
        print("AUGMIS Step 53F — READ-ONLY PUBLISHER OWNERSHIP INVENTORY")
        print("No assignments or mutations will be performed.\n")
        for p in publishers:
            tenant = db.get(Tenant, p.tenant_id) if p.tenant_id else None
            app_count = db.scalar(select(func.count(Application.id)).where(Application.publisher_id == p.id)) or 0
            owners = db.execute(
                select(User.email)
                .join(PublisherMembership, PublisherMembership.user_id == User.id)
                .join(PublisherMembershipRole, PublisherMembershipRole.membership_id == PublisherMembership.id)
                .join(Role, Role.id == PublisherMembershipRole.role_id)
                .where(
                    PublisherMembership.publisher_id == p.id,
                    PublisherMembership.status == "active",
                    User.status == "active",
                    Role.code == "publisher_owner",
                )
                .distinct()
            ).scalars().all()
            label = f"{tenant.name} [{tenant.id}]" if tenant else "UNASSIGNED"
            print(f"Publisher: {p.name} | id={p.id} | status={p.status}")
            print(f"  Organization: {label}")
            print(f"  Applications: {app_count}")
            print(f"  Active Publisher Owners: {', '.join(owners) or 'NONE'}")
            print()
        print(f"Total publishers: {len(publishers)}; pending: {sum(p.tenant_id is None for p in publishers)}")
        print("One workspace per tenant is enforced. Assign only after confirming legal ownership.")
        print("If two legacy publishers must be consolidated, DO NOT delete or re-parent applications automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
