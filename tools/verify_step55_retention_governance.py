"""AUGMIS Step 55: NONDESTRUCTIVE retention-governance assessment.

Runs policy validation; optionally invokes the existing DB retention-impact
reporter. This tool cannot approve or activate a policy, implement legal holds,
archive audit events, or purge records.

Usage from repo root:
  python -m tools.verify_step55_retention_governance
  python -m tools.verify_step55_retention_governance --with-db
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'docs' / 'AUGMIS_AUDIT_RETENTION_POLICY_DRAFT.json'
REQUIRED_DISABLED = ('autoDeletionEnabled', 'purgeApiEnabled', 'purgeJobEnabled')


def validate_policy(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(raw, dict) or raw.get('schemaVersion') != 'augmis.audit.retention.v1':
        raise ValueError('Unexpected or missing retention policy schema version.')
    days = raw.get('proposedOperationalRetentionDays')
    if isinstance(days, bool) or not isinstance(days, int) or not 30 <= days <= 3650:
        raise ValueError('Proposed assessment days must be an integer from 30 through 3650.')
    if raw.get('status') != 'draft_unapproved':
        raise ValueError('This Step 55 baseline only supports an unapproved policy draft.')
    for key in REQUIRED_DISABLED:
        if raw.get(key) is not False:
            raise ValueError(f'{key} must remain explicitly false.')
    for key in ('legalHoldRegistryStatus', 'legalHoldEnforcementStatus'):
        if raw.get(key) != 'not_implemented':
            raise ValueError(f'{key}: this baseline cannot assert legal-hold capabilities.')
    for key in ('immutableArchiveStatus', 'archiveVerificationStatus'):
        if raw.get(key) != 'not_configured':
            raise ValueError(f'{key}: this baseline cannot assert an archive capability.')
    if raw.get('approvedBy') is not None or raw.get('approvalDate') is not None:
        raise ValueError('Unapproved draft cannot carry approval metadata.')
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', type=Path, default=DEFAULT)
    parser.add_argument('--with-db', action='store_true', help='Run existing read-only database impact reporter')
    args = parser.parse_args()
    try:
        policy = validate_policy(args.policy)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print('[FAIL] Retention policy:', str(exc))
        return 1
    print('[PASS] Retention policy draft conforms to non-destructive baseline.')
    print(f"[ASSESSMENT ONLY] Proposed age: {policy['proposedOperationalRetentionDays']} days")
    print('[SAFE] No purge API, scheduled purge, legal hold, or immutable archive falsely claimed.')
    print('[PENDING] Legal/contractual approval, hold enforcement, and independently verified archives.')
    if args.with_db:
        result = subprocess.run(
            [sys.executable, '-m', 'tools.report_audit_retention', '--days',
             str(policy['proposedOperationalRetentionDays'])],
            cwd=ROOT, check=False,
        )
        return result.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
