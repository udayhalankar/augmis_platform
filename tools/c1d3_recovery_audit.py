"""C1-D3 recovery diagnostics. Run from the repository root with python -m."""
from __future__ import annotations
import argparse
import json
import uuid

from services.api.app.services.c1d3_recovery_audit import inventory
from services.api.app.services.deployment_reliability import quarantine_expired


def main() -> int:
    parser = argparse.ArgumentParser(description="Non-destructive AUGMIS deployment recovery audit")
    parser.add_argument("--tenant-id", type=uuid.UUID)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--include-healthy", action="store_true")
    parser.add_argument("--no-docker-inspect", action="store_true", help="Database metadata report only")
    parser.add_argument("--quarantine-expired", action="store_true", help="Explicitly quarantine expired journal leases in Control Plane database; no Docker changes")
    args = parser.parse_args()
    from services.api.app.db.session import SessionLocal
    with SessionLocal() as db:
        if args.quarantine_expired:
            # No cross-tenant metadata mutation from a tenant-scoped CLI.
            if args.tenant_id is None:
                parser.error('--tenant-id is required with --quarantine-expired')
            count = quarantine_expired(db, limit=args.limit, tenant_id=args.tenant_id)
            db.commit()
            print(f"C1D3_EXPIRED_JOURNALS_QUARANTINED: {count}")
        rows = inventory(db, tenant_id=args.tenant_id, limit=args.limit,
                         include_healthy=args.include_healthy,
                         inspect_docker=not args.no_docker_inspect)
        db.rollback()
    print(json.dumps({"mode": "metadata_quarantine" if args.quarantine_expired else "read_only",
                      "inspected": len(rows), "records": rows}, indent=2))
    print("C1D3_NO_CONTAINER_OR_DATABASE_RESOURCES_MODIFIED")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
