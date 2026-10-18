"""Read-only C1-C3 application host preflight. No Docker/container mutations."""
from __future__ import annotations
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from services.api.app.core.config import settings
from services.api.app.services.private_crud_runtime import signing_material
from services.api.app.services.aaps_deployment_contract import assess_manifest,route_contract
from services.api.app.services.aaps_declarative_schema import read_declarative_schema
from tools.validate_package import validate_application_package


def docker(*args):
    p=subprocess.run(['docker',*args],capture_output=True,text=True,timeout=25)
    if p.returncode != 0:raise ValueError('Docker preflight failed')
    return p.stdout.strip()


def main():
    parser=argparse.ArgumentParser(description='Read-only AUGMIS generic runtime readiness')
    parser.add_argument('--package',type=Path,required=True)
    args=parser.parse_args()
    if str(settings.app_env).lower() not in {'dev','development'}:
        raise SystemExit('STOP: generic C1-C3 requires a development environment')
    for flag in ('AUGMIS_C1C_GENERIC_RUNTIME_ENABLED','AUGMIS_C1C_DECLARED_SCHEMA_ENABLED',
                 'AUGMIS_C1B_DEV_DB_ENABLED','AUGMIS_C1B_DEV_UNQUOTED_VOLUME_OK'):
        if os.environ.get(flag)!='1':raise SystemExit('STOP: required flag unset: '+flag)
    for label, env in [('PostgreSQL','AUGMIS_C1B_POSTGRES_IMAGE_ID'),
                       ('Generic relay','AUGMIS_C1C_GENERIC_RELAY_IMAGE_ID')]:
        image=os.environ.get(env,'')
        if not re.fullmatch(r'sha256:[0-9a-f]{64}',image):
            raise SystemExit('STOP: missing immutable ID for '+label)
        if docker('image','inspect','--format','{{.Id}}',image)!=image:
            raise SystemExit('STOP: image digest drift for '+label)
    if docker('image','inspect','--format','{{.Config.User}}',os.environ['AUGMIS_C1C_GENERIC_RELAY_IMAGE_ID'])!='10002:10002':
        raise SystemExit('STOP: generic relay must run as user 10002')
    ingress=os.environ.get('AUGMIS_C1B_CRUD_INGRESS_NETWORK','')
    if not ingress or docker('network','inspect','--format','{{.Internal}}',ingress).lower()!='false':
        raise SystemExit('STOP: ingress bridge missing or internal')
    signing_material()  # verify key pair and permissions without printing secrets
    manifest=validate_application_package(args.package)['manifest']
    plan=assess_manifest(manifest)
    if not plan.requires_private_database or not read_declarative_schema(manifest) or not route_contract(manifest):
        raise SystemExit('STOP: supported PostgreSQL schema and gateway contract required')
    print('PASS: development mode, opt-in flags, immutable images, non-root relay, ingress, signing keys')
    print('PASS: independently validated AAPS schema and route contract:',manifest['metadata']['id'],manifest['metadata']['version'])
    print('NO Docker resources, database changes or deployments were created.')

if __name__=='__main__':main()
