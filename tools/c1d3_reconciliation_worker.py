"""AUGMIS C1-D3 bounded reconciliation worker. Run: python -m tools.c1d3_reconciliation_worker --tenant-id UUID --once"""
from __future__ import annotations

import argparse
import json
import time
import uuid

from services.api.app.services.c1d3_reconciliation_worker import reconcile_once


def main() -> int:
    parser = argparse.ArgumentParser(description='Tenant-scoped, non-destructive C1-D3 recovery worker')
    parser.add_argument('--tenant-id', type=uuid.UUID, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--once', action='store_true', help='Single iteration (default)')
    mode.add_argument('--watch', action='store_true', help='Repeat every interval, foreground')
    parser.add_argument('--interval-seconds', type=int, default=60)
    parser.add_argument('--limit', type=int, default=25)
    parser.add_argument('--lease-grace-seconds', type=int, default=900)
    parser.add_argument('--queued-stale-seconds', type=int, default=3600)
    parser.add_argument('--apply', action='store_true', help='Update expired journal metadata only; no Docker writes')
    args = parser.parse_args()
    if not 30 <= args.interval_seconds <= 3600:
        parser.error('--interval-seconds must be 30..3600')
    if args.watch and not args.apply:
        parser.error('--watch requires explicit --apply; use --once for dry-run')
    from services.api.app.db.session import SessionLocal
    try:
        while True:
            with SessionLocal() as db:
                result = reconcile_once(db, tenant_id=args.tenant_id, apply=args.apply,
                    limit=args.limit, lease_grace_seconds=args.lease_grace_seconds,
                    queued_stale_seconds=args.queued_stale_seconds)
                if not args.apply:
                    db.rollback()
            print(json.dumps(result, indent=2, sort_keys=True), flush=True)
            print('C1D3_NO_DOCKER_DATABASE_OR_APPLICATION_RESOURCES_MODIFIED', flush=True)
            if not args.watch:
                break
            time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
