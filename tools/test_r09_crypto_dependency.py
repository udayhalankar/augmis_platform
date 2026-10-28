"""R09: patched cryptography pin alignment and core crypto smoke contracts."""
from importlib.metadata import version
from pathlib import Path

from cryptography.fernet import Fernet, MultiFernet
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]

def test_cryptography_is_patched():
    major, minor, micro = map(int, version('cryptography').split('.')[:3])
    assert (major,minor,micro) == (50,0,2)

def test_platform_and_generated_runtime_share_patch_level():
    requirements = (ROOT/'requirements.txt').read_text('utf-8')
    generator = (ROOT/'services/api/app/services/c1d5_aaps_generator.py').read_text('utf-8')
    assert requirements.splitlines().count('cryptography==50.0.2')==1
    assert 'cryptography==50.0.2' in generator
    assert 'cryptography==46.0.4' not in generator
    assert 'cryptography>=43,<47' not in requirements

def test_fernet_and_multifernet_keyring_roundtrip():
    previous=Fernet(Fernet.generate_key()); active=Fernet(Fernet.generate_key())
    token=previous.encrypt(b'synthetic-credential')
    keyring=MultiFernet([active,previous])
    assert keyring.decrypt(token)==b'synthetic-credential'
    rotated=keyring.rotate(token)
    assert active.decrypt(rotated)==b'synthetic-credential'

def test_ed25519_sign_verify_roundtrip():
    priv=Ed25519PrivateKey.generate()
    payload=b'synthetic-runtime-assertion'
    priv.public_key().verify(priv.sign(payload),payload)

def test_aesgcm_backup_primitive_roundtrip():
    key=AESGCM.generate_key(bit_length=256)
    aead=AESGCM(key)
    nonce=b'0123456789ab'
    associated=b'augmis-test-only'
    ciphertext=aead.encrypt(nonce,b'synthetic backup',associated)
    assert aead.decrypt(nonce,ciphertext,associated)==b'synthetic backup'
