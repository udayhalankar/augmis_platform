"""AUGMIS Step 56: consolidated local regression and release-readiness runner.

Never commits, tags, pushes, changes database schema, or deletes records.
This is NOT an API security test runner; human-observed live negative HTTP
checks must be attested separately in the acceptance document.

Usage from repo root:
  python -m tools.verify_phase5_release --mode quick
  python -m tools.verify_phase5_release --mode full --evidence <audit.json>
  python -m tools.verify_phase5_release --mode full --acceptance docs/PHASE5_ACCEPTANCE_LOCAL.json --release-gate

A generated report records command identifiers / PASS / FAIL / SHA-256 of
stdout and stderr, not raw logs or secrets. Reports should not be committed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CHECKS = (
    'step53fPublisherOwnershipDisposition',
    'step54LiveTenantExport',
    'step54LivePlatformExport',
    'step54UnauthorizedTenantExport403',
    'step54UnauthorizedPlatformExport403',
    'step54JsonEvidenceChecksum',
    'step54CsvEvidenceChecksum',
    'step54ExportAuditEvent',
    'step55RetentionPolicyReviewed',
    'step55NoDeletionAndHoldGapAcknowledged',
    'step56RegressionSmokeTests',
    'step56DocumentationReviewed',
)


def digest(output: str) -> str:
    return hashlib.sha256(output.encode('utf-8', errors='replace')).hexdigest()


def execute(label: str, argv: list[str], *, timeout: int = 240) -> tuple[bool, dict, str]:
    print(f'[{label}]', ' '.join(argv))
    try:
        proc = subprocess.run(
            argv, cwd=ROOT, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=timeout, check=False,
        )
        passed = proc.returncode == 0
        result = {'name': label, 'passed': passed, 'exitCode': proc.returncode,
                  'stdoutSha256': digest(proc.stdout),
                  'stderrSha256': digest(proc.stderr)}
        print(f"  [{'PASS' if passed else 'FAIL'}] exit={proc.returncode}")
        if not passed:
            # Errors visible in the console, never copied to the persisted report.
            for line in (proc.stderr or proc.stdout).splitlines()[-6:]:
                print('   ', line[:400])
        return passed, result, proc.stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        print('  [FAIL]', type(exc).__name__, str(exc)[:300])
        return False, {'name': label, 'passed': False, 'errorType': type(exc).__name__}, ''


def acceptance_state(path: Path | None) -> tuple[bool, list[str]]:
    if path is None:
        return False, ['Acceptance file was not supplied.']
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        return False, [f'Could not read acceptance file: {type(exc).__name__}']
    if data.get('schemaVersion') != 'augmis.phase5.acceptance.v1':
        return False, ['Unexpected acceptance schema version.']
    checks = data.get('checks')
    if not isinstance(checks, dict):
        return False, ['Acceptance checks missing.']
    missing = [name for name in REQUIRED_CHECKS if checks.get(name) != 'passed']
    if not str(data.get('approver', '')).strip() or not str(data.get('approvalDate', '')).strip():
        missing.append('Approver and approval date are required.')
    if data.get('openRisks'):
        missing.append('Unresolved open risks require disposition before release freeze.')
    return len(missing) == 0, missing


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=('quick', 'full'), default='quick')
    p.add_argument('--evidence', type=Path, help='Previously downloaded JSON evidence bundle')
    p.add_argument('--acceptance', type=Path, help='Local acceptance document (not the template)')
    p.add_argument('--release-gate', action='store_true', help='Require clean git and complete manual acceptance')
    p.add_argument('--report', type=Path, default=None,
                   help='JSON results file. Default is data/phase5-verification/verification.json')
    args = p.parse_args()
    if args.release_gate and args.mode != 'full':
        p.error('--release-gate requires --mode full')
    if args.release_gate and not args.evidence:
        p.error('--release-gate requires --evidence for JSON digest verification')

    steps = [
        ('retention_policy', [sys.executable, '-m', 'tools.verify_step55_retention_governance']),
        ('phase4_rbac', [sys.executable, '-m', 'tools.verify_phase4_rbac']),
        ('phase4_rbac_matrix', [sys.executable, '-m', 'tools.verify_phase4_rbac_matrix']),
        ('publisher_owner_integrity', [sys.executable, '-m', 'tools.verify_publisher_owner_integrity']),
        ('single_publisher_workspace', [sys.executable, '-m', 'tools.verify_single_publisher_workspace']),
        ('step53b_application_audit', [sys.executable, '-m', 'tools.verify_step53b_application_audit']),
        ('step53f54_audit_exports', [sys.executable, '-m', 'tools.verify_step53f54']),
        ('audit_retention_impact', [sys.executable, '-m', 'tools.report_audit_retention', '--days', '365']),
    ]
    if args.evidence:
        steps.append(('audit_evidence_digest', [sys.executable, '-m', 'tools.verify_audit_evidence', str(args.evidence.resolve())]))
    if args.mode == 'full':
        steps += [
            ('backend_compile', [sys.executable, '-m', 'compileall', '-q', 'services/api/app', 'tools']),
            ('typescript', ['npx.cmd' if os.name == 'nt' else 'npx', 'tsc', '--noEmit']),
            ('next_build', ['npm.cmd' if os.name == 'nt' else 'npm', 'run', 'build']),
        ]
    records = []
    overall = True
    for name, argv in steps:
        # Frontend commands must run within apps/web, not the repository root.
        if name in ('typescript', 'next_build'):
            print(f'[{name}]', ' '.join(argv), '(cwd=apps/web)')
            try:
                result = subprocess.run(argv, cwd=ROOT / 'apps' / 'web', capture_output=True,
                                        text=True, encoding='utf-8', errors='replace',
                                        timeout=600, check=False)
                good = result.returncode == 0
                rec = {'name': name, 'passed': good, 'exitCode': result.returncode,
                       'stdoutSha256': digest(result.stdout), 'stderrSha256': digest(result.stderr)}
                print(f"  [{'PASS' if good else 'FAIL'}] exit={result.returncode}")
                if not good:
                    for line in (result.stderr or result.stdout).splitlines()[-6:]:
                        print('   ', line[:400])
            except (OSError, subprocess.TimeoutExpired) as exc:
                good = False
                rec = {'name': name, 'passed': False, 'errorType': type(exc).__name__}
                print('  [FAIL]', str(exc)[:300])
        else:
            good, rec, _ = execute(name, argv)
        records.append(rec)
        overall = overall and good

    migration_cur_ok, current_rec, current_text = execute('alembic_current', ['alembic', 'current'])
    migration_head_ok, head_rec, head_text = execute('alembic_heads', ['alembic', 'heads'])
    records.extend([current_rec, head_rec])
    def revisions(value: str) -> set[str]:
        return set(re.findall(r'(?m)^([0-9a-f]{10,16})(?:\s|$)', value))
    current = revisions(current_text)
    heads = revisions(head_text)
    migration_match = migration_cur_ok and migration_head_ok and len(current) == 1 and current == heads
    print('[{}] alembic revision consistency: current={} heads={}'.format(
        'PASS' if migration_match else 'FAIL', sorted(current), sorted(heads)))
    overall = overall and migration_match

    git_ok, git_rec, git_text = execute('git_status', ['git', 'status', '--porcelain'])
    records.append(git_rec)
    dirty = bool(git_text.strip())
    print('[{}] git working tree {}'.format('INFO' if not args.release_gate else ('FAIL' if dirty else 'PASS'),
                                             'dirty' if dirty else 'clean'))
    overall = overall and git_ok and (not dirty or not args.release_gate)

    manual_ok, missing = acceptance_state(args.acceptance)
    if args.release_gate:
        print('[{}] manual acceptance'.format('PASS' if manual_ok else 'BLOCKED'))
        for item in missing:
            print('  -', item)
        overall = overall and manual_ok
    else:
        print('[PENDING] Live negative authorization checks require manual acceptance evidence.')

    # Query legacy mapping state. The 1:1 checker verifies uniqueness, but
    # doesn't reject existing NULL publisher owners from the prior era.
    # Manual acceptance must include an approved disposition for these.
    if args.release_gate:
        print('[GATE] Manual publisher ownership disposition and risks must be accepted above.')
    report = {
        'schema': 'augmis.phase5.verification.v1',
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'mode': args.mode, 'releaseGate': args.release_gate,
        'passed': overall, 'gitDirty': dirty, 'alembicMatched': migration_match,
        'steps': records, 'manualAcceptanceComplete': manual_ok,
        'note': 'Command hashes are diagnostic only. No raw logs, tokens, or account data are stored. Live API negative tests are manual.',
    }
    out = args.report or (ROOT / 'data' / 'phase5-verification' / 'verification.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('Report saved:', out)
    print('[{}] Phase 5 {}'.format('PASS' if overall else 'FAIL', 'release gate' if args.release_gate else 'local checks'))
    return 0 if overall else 1


if __name__ == '__main__':
    raise SystemExit(main())
