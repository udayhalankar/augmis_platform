"""Read-only preflight: does not create Docker, DB, secrets or instances."""
from __future__ import annotations
import os
import re
import subprocess
import uuid
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey,Ed25519PublicKey


def inspect(*args):
    result=subprocess.run(['docker',*args],capture_output=True,text=True,timeout=30)
    if result.returncode != 0:
        raise RuntimeError('Docker inspection failed; check Docker Desktop and image/network existence')
    return result.stdout.strip()


def main():
    required=('AUGMIS_C1B_CRUD_PRIVATE_RUNTIME_ENABLED','AUGMIS_C1B_DEV_DB_ENABLED',
              'AUGMIS_C1B_DEV_SCHEMA_ENABLED','AUGMIS_C1B_DEV_UNQUOTED_VOLUME_OK')
    if any(os.environ.get(flag)!='1' for flag in required):
        raise RuntimeError('Required development opt-in flag is missing')
    app=os.environ.get('AUGMIS_C1B_CRUD_APPLICATION_ID','')
    if str(uuid.UUID(app))!=app:
        raise RuntimeError('Trusted CRUD application UUID not configured')
    prv=Path(os.environ['AUGMIS_C1B_CRUD_SIGNING_PRIVATE_KEY_FILE'])
    pub=Path(os.environ['AUGMIS_C1B_CRUD_SIGNING_PUBLIC_KEY_FILE'])
    if any(not p.is_absolute() or not p.is_file() or p.is_symlink() for p in (prv,pub)):
        raise RuntimeError('Development signing file(s) unavailable')
    private=serialization.load_pem_private_key(prv.read_bytes(),password=None)
    public=serialization.load_pem_public_key(pub.read_bytes())
    if not isinstance(private,Ed25519PrivateKey) or not isinstance(public,Ed25519PublicKey):
        raise RuntimeError('Ed25519 signing pair required')
    if private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)!=public.public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw):
        raise RuntimeError('Signing pair does not match')
    pg=os.environ['AUGMIS_C1B_POSTGRES_IMAGE_ID']
    relay=os.environ['AUGMIS_C1B_CRUD_RELAY_IMAGE_ID']
    if any(not re.fullmatch(r'sha256:[0-9a-f]{64}', value) for value in (pg,relay)):
        raise RuntimeError('Pinned immutable Docker image IDs are required')
    if inspect('image','inspect','--format','{{.Id}}',pg)!=pg:
        raise RuntimeError('PostgreSQL image identity mismatch')
    if inspect('image','inspect','--format','{{.Id}}',relay)!=relay:
        raise RuntimeError('Relay image identity mismatch')
    if inspect('image','inspect','--format','{{.Config.User}}',relay)!='10002:10002':
        raise RuntimeError('Relay must run as UID 10002')
    ingress=os.environ['AUGMIS_C1B_CRUD_INGRESS_NETWORK']
    if inspect('network','inspect','--format','{{.Internal}}',ingress).lower()!='false':
        raise RuntimeError('Ingress bridge must be non-internal')
    if inspect('network','inspect','--format','{{.Driver}}',ingress).lower()!='bridge':
        raise RuntimeError('Ingress network must be bridge')
    print('PASS: C1-B4 opt-in, signing files, pinned images, ingress network')
    print('NO containers, databases, volumes, migrations, Git changes or deployments were created.')

if __name__=='__main__':
    try: main()
    except (KeyError,ValueError,OSError,RuntimeError,subprocess.SubprocessError) as exc:
        print('FAIL:',type(exc).__name__,'(do not Open Application until resolved)')
        raise SystemExit(1) from exc
