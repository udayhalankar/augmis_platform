"""R05 isolated source/security tests: no real secrets, cloud, Docker or DB I/O."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from services.api.app.services.r05_secret_files import (
    SecretMaterialError, read_production_secret_file,
    validate_production_signing_file,
)


def _secret(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_production_secret_file_no_secret_leaks(tmp_path):
    secret = _secret(tmp_path, "jwt", "synthetic-not-actual-secret\n")
    if os.name != "posix":
        with pytest.raises(SecretMaterialError, match="R05_PRODUCTION_LINUX_REQUIRED"):
            read_production_secret_file(str(secret), purpose="jwt")
        return
    assert read_production_secret_file(str(secret), purpose="jwt") == "synthetic-not-actual-secret"
    secret.chmod(0o644)
    with pytest.raises(SecretMaterialError, match="R05_SECRET_FILE_INVALID") as error:
        read_production_secret_file(str(secret), purpose="jwt")
    assert "synthetic-not-actual-secret" not in str(error.value)


def test_production_secret_symlink_or_directory_rejected(tmp_path):
    if os.name != "posix":
        pytest.skip("Linux protected mounted secret-file contract")
    secret = _secret(tmp_path, "jwt", "secret-example")
    link = tmp_path / "key-symlink"
    link.symlink_to(secret)
    for path in (link, tmp_path, tmp_path / "not-found"):
        with pytest.raises(SecretMaterialError, match="R05_SECRET_FILE_INVALID"):
            read_production_secret_file(str(path), purpose="jwt")


def test_signing_key_metadata_enforced(tmp_path):
    private = _secret(tmp_path, "signing.pem", "x" * 96)
    if os.name != "posix":
        with pytest.raises(SecretMaterialError, match="R05_PRODUCTION_LINUX_REQUIRED"):
            validate_production_signing_file(private)
        return
    validate_production_signing_file(private)
    private.chmod(0o640)
    with pytest.raises(SecretMaterialError, match="R05_SIGNING_KEY_FILE_UNSAFE"):
        validate_production_signing_file(private)


def test_settings_requires_managed_production_files(tmp_path, monkeypatch):
    from services.api.app.core.config import Settings
    for name in ("DATABASE_URL", "JWT_SECRET", "SETTINGS_ENCRYPTION_KEY", "MAIL_PASSWORD", "RESEND_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)
    if os.name != "posix":
        pytest.skip("Production mounted file loading requires Linux")
    active_key = Fernet.generate_key().decode("ascii")
    options = dict(
        app_env="production",
        database_url_file=str(_secret(tmp_path,"database", "postgresql+psycopg://user:fake@internal/db")),
        jwt_secret_file=str(_secret(tmp_path,"jwt", "x"*48)),
        settings_encryption_key_file=str(_secret(tmp_path,"encryption", active_key)),
    )
    cfg = Settings(_env_file=None, **options)
    assert cfg.jwt_secret == "x"*48
    assert cfg.settings_encryption_key == active_key
    with pytest.raises(RuntimeError, match="R05_PRODUCTION_INLINE_SECRET_DENIED"):
        Settings(_env_file=None, **options, jwt_secret="inline-test")
    with pytest.raises(RuntimeError, match="R05_PRODUCTION_SECRET_FILE_REQUIRED"):
        Settings(_env_file=None, **{k:v for k,v in options.items() if k != "jwt_secret_file"})
    with pytest.raises(Exception):
        Settings(_env_file=None, **{**options,"database_url_file": str(tmp_path / "missing")})


def test_settings_development_values_preserved(monkeypatch):
    from services.api.app.core.config import Settings
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    cfg = Settings(_env_file=None, app_env="development", database_url="sqlite:///dev", jwt_secret="synthetic-development-key")
    assert cfg.database_url == "sqlite:///dev"
    assert cfg.jwt_secret == "synthetic-development-key"


def test_credential_keyring_requires_old_key_until_rotated(tmp_path, monkeypatch):
    if os.name != "posix":
        pytest.skip("Production keyring files require Linux")
    from services.api.app.services import platform_settings_service as svc
    old = Fernet.generate_key().decode("ascii")
    active = Fernet.generate_key().decode("ascii")
    stored = Fernet(old.encode()).encrypt(b"synthetic-smtp-token").decode()
    previous_file = _secret(tmp_path, "old", old)
    monkeypatch.setattr(svc, "settings", SimpleNamespace(app_env="production", settings_encryption_key=active))
    monkeypatch.setenv("SETTINGS_ENCRYPTION_PREVIOUS_KEY_FILES", str(previous_file))
    assert svc._decrypt_credential(stored) == "synthetic-smtp-token"
    rotated = svc.reencrypt_credential_ciphertext(stored)
    monkeypatch.delenv("SETTINGS_ENCRYPTION_PREVIOUS_KEY_FILES")
    assert svc._decrypt_credential(rotated) == "synthetic-smtp-token"
    with pytest.raises(svc.PlatformSettingsError, match="could not be decrypted"):
        svc._decrypt_credential(stored)


def test_invalid_previous_keyring_fails_closed(monkeypatch):
    from services.api.app.services import platform_settings_service as svc
    monkeypatch.setattr(svc, "settings", SimpleNamespace(app_env="production", settings_encryption_key=Fernet.generate_key().decode()))
    monkeypatch.setenv("SETTINGS_ENCRYPTION_PREVIOUS_KEY_FILES", "/not-present")
    with pytest.raises(svc.PlatformSettingsError, match="R05_PREVIOUS_KEYS_UNAVAILABLE"):
        svc._fernet()
