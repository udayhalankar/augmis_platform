"""Read-only Stage 53D organization/publisher integrity verification.

Run from AUGMIS repository root after alembic upgrade and source patch:
  python -m tools.verify_step53d_org_publisher
  python -m tools.verify_step53d_org_publisher --require-all-linked
"""
from __future__ import annotations

import argparse
import sys
from sqlalchemy import func, select
from services.api.app.db.session import SessionLocal
from services.api.app.models.iam import PublisherMembership
from services.api.app.models.platform import Publisher, Tenant
from services.api.app.services.publisher_ownership_service import _shared_active_owner_exists


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-all-linked", action="store_true")
    args = parser.parse_args()

    failures = []
    unassigned = []
    with SessionLocal() as db:
        publishers = list(db.scalars(select(Publisher).order_by(Publisher.name)))
        for p in publishers:
            if p.tenant_id is None:
                unassigned.append(p)
                print(f"[PENDING] {p.name} ({p.id}): organization unassigned")
                continue
            org = db.get(Tenant, p.tenant_id)
            if org is None or org.status != "active":
                failures.append(f"{p.name}: linked tenant missing or inactive")
                continue
            if not _shared_active_owner_exists(db, publisher_id=p.id, tenant_id=org.id):
                failures.append(f"{p.name}: no active Publisher Owner is a member of {org.name}")
                continue
            print(f"[PASS] {p.name} belongs to {org.name} ({org.id})")

        duplicates = db.execute(
            select(PublisherMembership.publisher_id, PublisherMembership.user_id,
                   func.count(PublisherMembership.id))
            .group_by(PublisherMembership.publisher_id, PublisherMembership.user_id)
            .having(func.count(PublisherMembership.id) > 1)
        ).all()
        if duplicates:
            failures.extend(f"Duplicate publisher membership: publisher={p}, user={u}, count={c}"
                            for p, u, c in duplicates)
    print(f"\nPublishers: {len(publishers)} | Linked: {len(publishers) - len(unassigned)}"
          f" | Pending mapping: {len(unassigned)} | Violations: {len(failures)}")
    if args.require_all_linked and unassigned:
        failures.append(f"{len(unassigned)} publishers have not been assigned")
    for item in failures:
        print("[FAIL]", item)
    if failures:
        print("STEP 53D PUBLISHER OWNERSHIP: FAILED")
        return 1
    if unassigned:
        print("STEP 53D PUBLISHER OWNERSHIP: PARTIAL (existing publisher mappings pending)")
    else:
        print("STEP 53D PUBLISHER OWNERSHIP: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
