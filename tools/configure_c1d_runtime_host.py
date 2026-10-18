"""One-time durable C1-D1 development host profile bootstrap.

No Docker/PG resource changes. No private key contents in profile or stdout.
By default uses the service account's home directory: ~/.augmis/runtime-host.json.
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.api.app.core.runtime_host import default_profile_path, read_profile


def inspect_image(tag: str) -> str:
    p = subprocess.run(['docker', 'image', 'inspect', tag, '--format', '{{.Id}}'],
                       capture_output=True, text=True, timeout=15)
    if p.returncode:
        raise ValueError('C1D_IMAGE_NOT_AVAILABLE')
    return p.stdout.strip()


def write_profile(profile: dict, destination: Path, replace: bool) -> None:
    if destination.is_symlink() or not destination.is_absolute():
        raise ValueError('C1D_DESTINATION_INVALID')
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.exists() and not replace:
        raise ValueError('C1D_PROFILE_ALREADY_EXISTS (use --replace only after review)')
    # Never rename an existing configuration out of the way without preserving it.
    if destination.exists():
        backup = destination.with_suffix('.json.previous')
        if backup.exists():
            raise ValueError('C1D_BACKUP_EXISTS (manual review required)')
        import shutil
        shutil.copy2(destination, backup)
    temporary = destination.with_suffix('.json.tmp')
    if temporary.exists():
        raise ValueError('C1D_TEMP_FILE_EXISTS')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(profile, out, indent=2)
            out.write('\n')
        read_profile(temporary)  # strict schema before publication
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def main():
    ap = argparse.ArgumentParser(description='One-time AUGMIS dev runtime profile setup')
    ap.add_argument('--signing-private', type=Path, required=True)
    ap.add_argument('--signing-public', type=Path, required=True)
    ap.add_argument('--ingress-network', default='augmis-crud-dev-ingress')
    ap.add_argument('--crud-application-id', help='Retain existing legacy CRUD deployment compatibility')
    ap.add_argument('--replace', action='store_true')
    args = ap.parse_args()
    profile = {
        'schemaVersion': 1, 'environment': 'development',
        'postgresImageId': inspect_image('postgres:15-alpine'),
        'genericRelayImageId': inspect_image('augmis-generic-relay:dev'),
        'ingressNetwork': args.ingress_network,
        'signingPrivateKeyFile': str(args.signing_private.resolve()),
        'signingPublicKeyFile': str(args.signing_public.resolve()),
        'allowDevelopmentUnquotedVolumes': True,
        'enableLegacyCrud': bool(args.crud_application_id),
    }
    if args.crud_application_id:
        profile['legacyCrudApplicationId'] = args.crud_application_id
        profile['legacyCrudRelayImageId'] = inspect_image('augmis-crud-relay:dev')
    write_profile(profile, default_profile_path(), args.replace)
    print('PASS: durable development runtime-host profile installed outside the repository')
    print('PROFILE:', default_profile_path())
    print('No Docker resources, application records, DB rows or Git files modified.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        # Diagnostics never print command stderr, secret bytes or arbitrary paths.
        code = str(exc)
        print('STOP:', code if code.startswith('C1D_') else 'C1D_PROFILE_CREATION_FAILED')
        sys.exit(1)
