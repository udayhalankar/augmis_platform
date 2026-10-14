"""Explicit trusted control-plane worker. No HTTP user impersonation."""
import argparse
import os
import socket
import time
from services.api.app.db.session import SessionLocal
from services.api.app.services.runtime_automation_service import (
    plan_upgrades, claim_one, execute_one,
)

def run_once(*, dry_run: bool = True, limit: int = 100):
    with SessionLocal() as db:
        planned = plan_upgrades(db, dry_run=dry_run, limit=limit)
        print(f"[PLAN] {'DRY RUN' if dry_run else 'ENQUEUED'} {len(planned)} eligible upgrades")
        for item in planned:
            print(f"  instance={item['instanceId']} from={item['from']} to={item['to']}")
    if dry_run:
        return
    with SessionLocal() as db:
        job_id = claim_one(db, f"{socket.gethostname()}:{os.getpid()}")
    if job_id:
        with SessionLocal() as db:
            status = execute_one(db, job_id)
        print(f"[JOB] {job_id} {status}")
    else:
        print("[IDLE] No queued jobs")

def main():
    parser = argparse.ArgumentParser(description="AUGMIS B2 upgrade worker (off by default)")
    parser.add_argument("--enqueue-and-run", action="store_true",
                        help="Explicitly enqueue eligible upgrades and execute one job")
    parser.add_argument("--loop", action="store_true", help="Run continuously, requires --enqueue-and-run")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if args.loop and not args.enqueue_and_run:
        parser.error("--loop requires --enqueue-and-run")
    if not 30 <= args.interval <= 3600:
        parser.error("--interval must be 30..3600 seconds")
    while True:
        run_once(dry_run=not args.enqueue_and_run, limit=args.limit)
        if not args.loop:
            break
        time.sleep(args.interval)

if __name__ == "__main__":
    main()
