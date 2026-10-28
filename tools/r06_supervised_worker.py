"""R06: trusted out-of-process supervisor for existing AUGMIS workers.

Run under an OS process supervisor (e.g. systemd). No implicit Docker recovery,
job replay, migration, or production enablement. Dedicated PostgreSQL session-level
advisory ownership prevents two processes handling the same worker role at once.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

# Stable, explicitly reserved app-defined lock IDs. Never use Python hash():
# it is randomized between processes.
R06_LOCK_IDS = {
    'qualification': 829_606_001,
    'auto-upgrade': 829_606_002,
    'reconciliation': 829_606_003,
}


def _event(role: str, code: str, **fields) -> None:
    safe = {k: v for k, v in fields.items() if k in ('result', 'count', 'tenantId')}
    print(json.dumps({'component': 'augmis-r06-worker', 'role': role, 'code': code,
        'time': datetime.now(timezone.utc).isoformat(), **safe}, sort_keys=True), flush=True)


def _systemd_notify(message: str) -> None:
    """Optional Linux watchdog integration; no dependency and no error disclosure."""
    address = os.environ.get('NOTIFY_SOCKET', '')
    if not address or os.name != 'posix':
        return
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            if address.startswith('@'):
                address = '\0' + address[1:]
            sock.connect(address)
            sock.send(message.encode('ascii'))
    except OSError:
        pass  # OS supervisor owns process exit/health detection.


def _database_session():
    from services.api.app.db.session import SessionLocal
    return SessionLocal()


@contextmanager
def exclusive_role(engine, role: str):
    """Hold a dedicated connection until the worker terminates.

    The lock is session-scoped (pg_try_advisory_lock) and MUST NOT be acquired
    using a pooled Session that can be returned between work iterations.
    """
    from sqlalchemy import text
    key = R06_LOCK_IDS[role]
    with engine.connect() as connection:
        if connection.dialect.name != 'postgresql':
            raise RuntimeError('R06_POSTGRESQL_REQUIRED')
        got = connection.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': key}).scalar()
        connection.commit()
        if got is not True:
            raise RuntimeError('R06_WORKER_ALREADY_OWNED')
        try:
            yield
        finally:
            try:
                connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': key})
                connection.commit()
            except Exception:
                connection.invalidate()


def run_cycle(args, *, worker_id: str) -> str:
    """Existing domain engines remain the only source of business transitions."""
    with _database_session() as db:
        if args.role == 'qualification':
            from services.api.app.services.c1d2_automatic_qualification import (
                worker_one, quarantine_interrupted_smokes)
            if args.quarantine_stale:
                count = quarantine_interrupted_smokes(db,
                    older_than_seconds=args.stale_after, limit=args.batch_limit)
                _event(args.role, 'R06_STALE_REVIEW', count=count)
                return 'REVIEW_COMPLETE'  # Never launch an unrelated Docker smoke cycle.
            return worker_one(db)
        if args.role == 'auto-upgrade':
            from services.api.app.services.runtime_automation_service import (
                plan_upgrades, claim_one, execute_one)
            if args.plan_upgrades:
                plan_upgrades(db, dry_run=False, limit=args.batch_limit)
            claim = claim_one(db, worker_id)
            if claim is None:
                return 'IDLE'
            return execute_one(db, claim, expected_worker_id=worker_id)
        from services.api.app.services.c1d3_reconciliation_worker import reconcile_once
        report = reconcile_once(db, tenant_id=args.tenant_id, apply=args.apply_reconciliation,
            limit=args.batch_limit)
        _event(args.role, 'R06_RECONCILIATION_SCAN', count=report['quarantined'],
               tenantId=str(args.tenant_id))
        return 'RECONCILIATION_COMPLETE'


def parser():
    p = argparse.ArgumentParser(description='AUGMIS R06 supervised trusted worker')
    p.add_argument('--role', required=True, choices=tuple(R06_LOCK_IDS))
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--once', action='store_true')
    mode.add_argument('--watch', action='store_true')
    p.add_argument('--interval', type=int, default=30)
    p.add_argument('--batch-limit', type=int, default=25)
    p.add_argument('--tenant-id', type=uuid.UUID)
    p.add_argument('--apply-reconciliation', action='store_true')
    p.add_argument('--plan-upgrades', action='store_true')
    p.add_argument('--quarantine-stale', action='store_true')
    p.add_argument('--stale-after', type=int, default=14400)
    return p


def validate_args(args) -> None:
    if not 5 <= args.interval <= 3600 or not 1 <= args.batch_limit <= 100:
        raise ValueError('R06_WORKER_OPTIONS_INVALID')
    if args.role == 'reconciliation' and args.tenant_id is None:
        raise ValueError('R06_TENANT_REQUIRED')
    if args.role != 'reconciliation' and (args.tenant_id or args.apply_reconciliation):
        raise ValueError('R06_RECONCILIATION_OPTIONS_INVALID')
    if args.plan_upgrades and args.role != 'auto-upgrade':
        raise ValueError('R06_UPGRADE_OPTIONS_INVALID')
    if args.quarantine_stale and args.role != 'qualification':
        raise ValueError('R06_QUALIFICATION_OPTIONS_INVALID')
    if not 3600 <= args.stale_after <= 604800:
        raise ValueError('R06_STALE_WINDOW_INVALID')
    # A periodic operator-authorized quarantine cannot silently begin after reboot.
    if args.watch and (args.apply_reconciliation or args.quarantine_stale):
        raise ValueError('R06_REVIEW_OPERATIONS_REQUIRE_ONCE')


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        validate_args(args)
        # A worker process must not circumvent the API's existing production gate.
        from services.api.app.services.security_release_gate import require_safe_runtime_exposure
        require_safe_runtime_exposure()
        from services.api.app.db.session import engine
        worker_id = f'r06:{args.role}:{uuid.uuid4().hex[:20]}'
        active = True
        def stop(_signum, _frame):
            nonlocal active
            active = False
        signal.signal(signal.SIGTERM, stop)
        if hasattr(signal, 'SIGINT'):
            signal.signal(signal.SIGINT, stop)
        with exclusive_role(engine, args.role):
            _event(args.role, 'R06_WORKER_OWNERSHIP_ACQUIRED')
            _systemd_notify('READY=1')
            while active:
                try:
                    result = run_cycle(args, worker_id=worker_id)
                    _event(args.role, 'R06_WORK_CYCLE', result=result)
                except Exception:
                    # Do not print raw exceptions: driver/Docker errors can carry secrets.
                    _event(args.role, 'R06_WORK_CYCLE_FAILED')
                    return 2  # Let the OS supervisor restart the failed process.
                _systemd_notify('WATCHDOG=1')
                if args.once:
                    break
                stop_at = time.monotonic() + args.interval
                while active and time.monotonic() < stop_at:
                    time.sleep(min(.5, max(0.0, stop_at - time.monotonic())))
        _event(args.role, 'R06_WORKER_STOPPED')
        return 0
    except Exception:
        _event(args.role, 'R06_WORKER_STARTUP_FAILED')
        return 2


if __name__ == '__main__':
    sys.exit(main())
