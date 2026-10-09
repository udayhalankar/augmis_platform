"""Read-only DB verification of organization/publisher 1:1 integrity."""
from __future__ import annotations
from sqlalchemy import select, func
from services.api.app.db.session import SessionLocal
from services.api.app.models.platform import Publisher, Tenant


def main() -> None:
    with SessionLocal() as db:
        duplicates = db.execute(
            select(Publisher.tenant_id, func.count(Publisher.id))
            .where(Publisher.tenant_id.is_not(None))
            .group_by(Publisher.tenant_id)
            .having(func.count(Publisher.id) > 1)
        ).all()
        records = db.execute(
            select(Publisher.name, Publisher.status, Publisher.tenant_id, Tenant.name)
            .outerjoin(Tenant, Tenant.id == Publisher.tenant_id)
            .order_by(Publisher.name)
        ).all()
        for pub_name, status, org_id, org_name in records:
            state = "MAPPING PENDING" if org_id is None else "LINKED"
            print(f"[{state}] {pub_name} ({status}) -> {org_name or 'unassigned'}")
        if duplicates:
            for tid, count in duplicates:
                print(f"[FAIL] Tenant {tid} has {count} workspaces")
            raise SystemExit(1)
        print(f"[PASS] 1:1 integrity; publishers={len(records)}; pending={sum(r[2] is None for r in records)}")

if __name__ == "__main__":
    main()
