"""C1-D2 trusted qualification worker. Start in a supervised control-plane environment.

Runs ONLY pending rows enqueued by the authenticated package-build route.
Never serves HTTP, bypasses publisher permissions, or modifies tenant databases.
Run: python -m tools.c1d2_qualification_worker --once
     python -m tools.c1d2_qualification_worker --watch
"""
import argparse
import time
from services.api.app.db.session import SessionLocal
from services.api.app.core.config import settings
from services.api.app.services.c1d2_automatic_qualification import worker_one, QualificationGateError


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--once', action='store_true')
    group.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    if str(settings.app_env).lower() not in {'development', 'dev'}:
        raise SystemExit('STOP: C1D2_WORKER_DEVELOPMENT_ONLY')
    while True:
        try:
            with SessionLocal() as db:
                result = worker_one(db)
            print('C1-D2 worker:', result, flush=True)
        except QualificationGateError as exc:
            raise SystemExit('STOP: ' + exc.code) from exc
        if args.once:
            return
        time.sleep(5 if result != 'IDLE' else 10)


if __name__ == '__main__':
    main()
