"""Persistent development-process wrapper for the EXISTING C1-D2 trusted worker.

No new qualification engine, no HTTP entry point, no schema alteration.
Launch under Windows Task Scheduler to process pending builds automatically.
Worker_one alone makes the durable claim, runs the disposable checks and saves
trusted qualification evidence in PostgreSQL.
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path

from services.api.app.db.session import get_db
from services.api.app.services.c1d2_automatic_qualification import worker_one


def run_one() -> str:
    provider = get_db()
    try:
        session = next(provider)
        return worker_one(session)
    finally:
        provider.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--poll-seconds', type=int, default=20)
    parser.add_argument('--log-file', default='')
    args = parser.parse_args()
    if not 5 <= args.poll_seconds <= 300:
        parser.error('--poll-seconds must be 5 through 300')
    log_file = args.log_file or str(Path.home() / 'AUGMIS_C1D2_WORKER.log')
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_file, level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s')
    logging.info('Existing C1-D2 qualification worker loop started. PID=%s', os.getpid())
    # DB claim uses pending_smoke + started_at IS NULL and SKIP LOCKED;
    # already-started, failed or completed qualifications are NEVER replayed.
    while True:
        try:
            outcome = run_one()
            if outcome != 'IDLE':
                logging.info('Existing C1-D2 worker returned %s', outcome)
            if outcome not in {'IDLE', 'PASS', 'FAIL'}:
                logging.warning('Unexpected worker outcome %s', outcome)
            delay = 1 if outcome == 'PASS' else args.poll_seconds
        except KeyboardInterrupt:
            logging.info('Worker stopped by operator')
            return
        except Exception as error:
            # Do not print DSNs, tokens, environment variables or exception bodies.
            logging.error('Qualification runner exception type=%s', type(error).__name__)
            delay = args.poll_seconds
        time.sleep(delay)


if __name__ == '__main__':
    main()
