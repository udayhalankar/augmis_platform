"""Create a new development-only Ed25519 pair outside AUGMIS repository.

Does not contact Docker, PostgreSQL, the control plane, or a remote network.
Never overwrite existing material or print private key bytes.
"""
import argparse
import csv
import os
import platform
import subprocess
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def windows_sid():
    raw = subprocess.run(['whoami','/user','/fo','csv','/nh'],capture_output=True,text=True,check=True).stdout
    return next(csv.reader(raw.splitlines()))[1]


def secure_folder(directory):
    if platform.system() == 'Windows':
        sid=windows_sid()
        for args in (["icacls",str(directory),"/inheritance:r"],
                     ["icacls",str(directory),"/grant:r",f"*{sid}:(OI)(CI)F"]):
            subprocess.run(args,capture_output=True,text=True,check=True)
    else:
        directory.chmod(0o700)


def exclusive_file(path,contents):
    fd=os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd,'wb') as f:
        f.write(contents)
        f.flush()
        os.fsync(f.fileno())


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--directory',required=True)
    opts=ap.parse_args()
    directory=Path(opts.directory).absolute()
    if directory.is_symlink() or any(parent.is_symlink() for parent in directory.parents):
        raise SystemExit('STOP: secret path cannot contain symlinks')
    private=directory/'crud-private.pem'
    public=directory/'crud-public.pem'
    if private.exists() or public.exists():
        raise SystemExit('STOP: existing signing files; nothing overwritten')
    if not directory.exists():
        directory.mkdir(parents=True,mode=0o700)
    secure_folder(directory)
    key=Ed25519PrivateKey.generate()
    private_bytes=key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    public_bytes=key.public_key().public_bytes(serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    exclusive_file(private,private_bytes)
    exclusive_file(public,public_bytes)
    print('PASS: New development signing pair created outside repository.')
    print('Private key path:',private)
    print('Public key path:',public)
    print('Never upload, commit or share either key file.')

if __name__ == '__main__':
    main()
