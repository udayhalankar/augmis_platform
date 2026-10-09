"""Step 54 READ-ONLY retention-impact assessment. NEVER deletes events.

Usage:
    python -m tools.report_audit_retention --days 365

This does NOT implement automatic deletion or legal-hold exceptions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select
from services.api.app.db.session import SessionLocal
from services.api.app.models.audit import AuditEvent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=365)
    args = parser.parse_args()
    if not 30 <= args.days <= 3650:
        parser.error('--days must be between 30 and 3650')
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    with SessionLocal() as db:
        all_events = db.scalar(select(func.count(AuditEvent.id))) or 0
        older = db.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.created_at < cutoff)) or 0
        newest = db.scalar(select(func.max(AuditEvent.created_at)))
        oldest = db.scalar(select(func.min(AuditEvent.created_at)))
    print(f'[READ ONLY] Audit retention impact — proposed age: {args.days} days')
    print('Total events:', all_events, '| Older than cutoff:', older)
    print('Oldest:', oldest, '| Newest:', newest)
    print('NO records deleted. Set legal-hold, retention and immutable-archive policy before implementing purge.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
