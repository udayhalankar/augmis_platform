"""Read-only AAPS capability report: no containers, database or network I/O.

Usage: python tools/check_c1c_aaps_compatibility.py D:\\MyApp.zip
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.validate_package import validate_application_package, PackageValidationError
from services.api.app.services.aaps_deployment_contract import (
    assess_manifest, fail_closed_if_unimplemented, DeploymentContractError,
)


def main() -> int:
    p=argparse.ArgumentParser(description='Read-only AAPS deployment contract report')
    p.add_argument('package',type=Path)
    args=p.parse_args()
    print('=== AUGMIS C1-C AAPS CAPABILITY REPORT (READ ONLY) ===')
    try:
        report=validate_application_package(args.package)
        manifest=report['manifest']
        plan=assess_manifest(manifest)
    except (PackageValidationError,DeploymentContractError,ValueError,OSError) as exc:
        print('PACKAGE: FAILED')
        print('REASON:',exc)
        return 2
    print('PACKAGE: VALID')
    print('APP_KEY:',manifest['metadata']['id'])
    print('VERSION:',manifest['metadata']['version'])
    print('SERVICE:',plan.service_name,'PORT:',plan.service_port,'HEALTH:',plan.health_path)
    print('AUTH:',plan.authentication)
    print('DATABASE:',f'{plan.database_engine} {plan.database_version}' if plan.requires_private_database else 'none')
    print('MIGRATION_CONTRACT:', 'declared' if plan.has_migration_contract else 'not declared')
    print('GATEWAY_ROUTES:', 'declared' if plan.has_route_contract else 'not declared')
    try:
        fail_closed_if_unimplemented(manifest,legacy_crud=(manifest['metadata']['id']=='augmis-crud-reference'))
    except DeploymentContractError as exc:
        print('LIVE_DEPLOYMENT_SUPPORT: NOT READY')
        print('BLOCKER:',exc)
        print('No runtime resources were created.')
        return 3
    print('LIVE_DEPLOYMENT_SUPPORT: Existing supported path (actual runtime acceptance still required)')
    print('No runtime resources were created.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
