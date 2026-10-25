# services/api/app/services/platform_settings_service.py
from __future__ import annotations

from datetime import datetime, timezone
import os
import uuid

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from services.api.app.services.r05_secret_files import read_production_secret_file
from sqlalchemy.orm import Session

from services.api.app.core.config import settings
from services.api.app.models.platform_settings import PlatformEmailSettings
from services.api.app.schemas.platform_settings import PlatformEmailSettingsUpdate
from services.api.app.services.email_service import (
    MailConfiguration,
    mail_configuration_from_env,
)


class PlatformSettingsError(Exception):
    pass


VALID_EMAIL_PROVIDERS = {"resend", "custom"}


def _fernet() -> MultiFernet:
    """Use active key for writes; permit explicitly retained prior keys for reads.

    Credentials are NEVER transparently re-encrypted in ordinary requests.
    Rotating persisted DB ciphertext requires an audited, backed-up operation.
    """
    prod = str(settings.app_env).strip().lower() in ("production", "prod")
    if prod:
        # Production Settings loads only managed mounted key files.
        raw_key = str(settings.settings_encryption_key or "").strip()
        paths = os.environ.get("SETTINGS_ENCRYPTION_PREVIOUS_KEY_FILES", "").strip()
        if paths and (paths.startswith(",") or paths.endswith(",") or ",," in paths):
            raise PlatformSettingsError("R05_PREVIOUS_KEYS_INVALID")
        previous = [] if not paths else [item.strip() for item in paths.split(",")]
        if len(previous) > 3 or len(set(previous)) != len(previous):
            raise PlatformSettingsError("R05_PREVIOUS_KEYS_INVALID")
        try:
            materials = [raw_key] + [
                read_production_secret_file(path, purpose="settings")
                for path in previous
            ]
        except Exception:
            raise PlatformSettingsError("R05_PREVIOUS_KEYS_UNAVAILABLE") from None
    else:
        materials = [str(settings.settings_encryption_key or "").strip()]
    if not materials[0]:
        raise PlatformSettingsError("SETTINGS_ENCRYPTION_KEY is not configured.")
    try:
        if len(set(materials)) != len(materials):
            raise ValueError("duplicate key")
        return MultiFernet([Fernet(k.encode("utf-8")) for k in materials])
    except Exception:
        raise PlatformSettingsError("SETTINGS_ENCRYPTION_KEY is invalid.") from None


def reencrypt_credential_ciphertext(ciphertext: str) -> str:
    """Pure transformation for a separately authorized transactional rotation.

    Caller must first verify DB backups and transaction rollback procedures;
    this helper never performs any database write by itself.
    """
    try:
        return _fernet().rotate(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise PlatformSettingsError("Stored email credential could not be decrypted.") from None


def _encrypt_credential(value: str) -> str:
    return (
        _fernet()
        .encrypt(value.encode("utf-8"))
        .decode("utf-8")
    )


def _decrypt_credential(value: str) -> str:
    try:
        return (
            _fernet()
            .decrypt(value.encode("utf-8"))
            .decode("utf-8")
        )
    except InvalidToken as error:
        raise PlatformSettingsError(
            "Stored email credential could not be decrypted."
        ) from error


def get_platform_email_settings(
    db: Session,
) -> PlatformEmailSettings | None:
    return db.get(PlatformEmailSettings, 1)


def _normalise_provider(provider: str) -> str:
    value = str(provider or "").strip().lower()

    if value not in VALID_EMAIL_PROVIDERS:
        raise PlatformSettingsError(
            "Unsupported email provider."
        )

    return value


def _validate_transport(
    *,
    enabled: bool,
    host: str,
    from_email: str,
    use_starttls: bool,
    use_ssl: bool,
    username: str,
    credential: str,
) -> None:
    if use_ssl and use_starttls:
        raise PlatformSettingsError(
            "SSL/TLS and STARTTLS cannot both be enabled."
        )

    if enabled and not host.strip():
        raise PlatformSettingsError(
            "SMTP host is required when email delivery is enabled."
        )

    if enabled and not from_email.strip():
        raise PlatformSettingsError(
            "Sender email is required when email delivery is enabled."
        )

    if bool(username.strip()) != bool(credential):
        raise PlatformSettingsError(
            "SMTP username and credential must either both be configured or both be empty."
        )


def get_effective_mail_configuration(
    db: Session,
) -> tuple[MailConfiguration, str, str]:
    row = get_platform_email_settings(db)

    if not row:
        config = mail_configuration_from_env()
        provider = (
            "resend"
            if config.host.lower() == "smtp.resend.com"
            else "custom"
        )
        return config, "environment", provider

    credential = (
        _decrypt_credential(row.credential_ciphertext)
        if row.credential_ciphertext
        else ""
    )

    config = MailConfiguration(
        enabled=row.enabled,
        host=row.host,
        port=row.port,
        username=row.username,
        password=credential,
        from_email=row.from_email,
        from_name=row.from_name,
        use_starttls=row.use_starttls,
        use_ssl=row.use_ssl,
        timeout_seconds=row.timeout_seconds,
    )

    _validate_transport(
        enabled=config.enabled,
        host=config.host,
        from_email=config.from_email,
        use_starttls=config.use_starttls,
        use_ssl=config.use_ssl,
        username=config.username,
        credential=config.password,
    )

    return config, "database", row.provider


def platform_email_settings_payload(db: Session) -> dict:
    row = get_platform_email_settings(db)

    if not row:
        config = mail_configuration_from_env()
        provider = (
            "resend"
            if config.host.lower() == "smtp.resend.com"
            else "custom"
        )
        return {
            "provider": provider,
            "enabled": config.enabled,
            "host": config.host,
            "port": config.port,
            "username": config.username,
            "credentialConfigured": bool(config.password),
            "fromEmail": config.from_email,
            "fromName": config.from_name,
            "useStarttls": config.use_starttls,
            "useSsl": config.use_ssl,
            "timeoutSeconds": config.timeout_seconds,
            "source": "environment",
            "updatedAt": None,
        }

    return {
        "provider": row.provider,
        "enabled": row.enabled,
        "host": row.host,
        "port": row.port,
        "username": row.username,
        "credentialConfigured": bool(row.credential_ciphertext),
        "fromEmail": row.from_email,
        "fromName": row.from_name,
        "useStarttls": row.use_starttls,
        "useSsl": row.use_ssl,
        "timeoutSeconds": row.timeout_seconds,
        "source": "database",
        "updatedAt": row.updated_at,
    }


def update_platform_email_settings(
    db: Session,
    *,
    payload: PlatformEmailSettingsUpdate,
    updated_by_user_id: uuid.UUID,
) -> PlatformEmailSettings:
    provider = _normalise_provider(payload.provider)
    row = get_platform_email_settings(db)

    existing_credential = ""

    if row and row.credential_ciphertext:
        existing_credential = _decrypt_credential(
            row.credential_ciphertext
        )
    elif not row and settings.mail_password:
        # First save can safely migrate the current env credential
        # into encrypted database storage.
        existing_credential = settings.mail_password

    supplied_credential = str(payload.credential or "")

    if payload.clear_credential:
        effective_credential = ""
        encrypted_credential = None
    elif supplied_credential:
        effective_credential = supplied_credential
        encrypted_credential = _encrypt_credential(
            supplied_credential
        )
    elif existing_credential:
        effective_credential = existing_credential
        encrypted_credential = (
            row.credential_ciphertext
            if row and row.credential_ciphertext
            else _encrypt_credential(existing_credential)
        )
    else:
        effective_credential = ""
        encrypted_credential = None

    host = str(payload.host or "").strip()
    username = str(payload.username or "").strip()
    port = payload.port
    use_ssl = payload.use_ssl
    use_starttls = payload.use_starttls

    if provider == "resend":
        host = "smtp.resend.com"
        username = "resend"
        port = 465
        use_ssl = True
        use_starttls = False

    _validate_transport(
        enabled=payload.enabled,
        host=host,
        from_email=str(payload.from_email),
        use_starttls=use_starttls,
        use_ssl=use_ssl,
        username=username,
        credential=effective_credential,
    )

    if not row:
        row = PlatformEmailSettings(id=1)
        db.add(row)

    row.provider = provider
    row.enabled = payload.enabled
    row.host = host
    row.port = port
    row.username = username
    row.credential_ciphertext = encrypted_credential
    row.from_email = str(payload.from_email).strip()
    row.from_name = str(payload.from_name).strip()
    row.use_starttls = use_starttls
    row.use_ssl = use_ssl
    row.timeout_seconds = payload.timeout_seconds
    row.updated_by_user_id = updated_by_user_id
    row.updated_at = datetime.now(timezone.utc)

    db.flush()
    return row
