"""Read-only C1-D1 host readiness. Run from any fresh PowerShell terminal."""
from __future__ import annotations
import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.api.app.services.runtime_host_readiness import check_runtime_host
from services.api.app.core.runtime_host import default_profile_path


def main() -> int:
    result = check_runtime_host()
    print('AUGMIS C1-D1 Runtime Host')
    print('Profile:', default_profile_path())
    print('State:', result.state)
    print('Code:', result.code)
    print('Read-only: no Docker/DB/container/network changes')
    return 0 if result.ready else 1

if __name__ == '__main__':
    raise SystemExit(main())
