from pathlib import Path
import ipaddress
import re
from urllib.parse import urlsplit

from pydantic import model_validator

from services.api.app.services.r05_secret_files import read_production_secret_file

from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


from services.api.app.core.runtime_host import hydrate_runtime_profile

# Load the durable, non-secret runtime host profile before importing any routes.
hydrate_runtime_profile()


class Settings(BaseSettings):

    app_name: str = "AUGMIS SaaS Platform"

    app_env: str = "development"

    database_url: str

    package_storage_path: str = "data/packages"

    max_upload_size_mb: int = 250

    jwt_secret: str

    jwt_algorithm: str = "HS256"

    access_token_minutes: int = 60  # Legacy setting; new sessions use session_access_minutes.
    session_access_minutes: int = 10
    session_default_idle_minutes: int = 30
    session_absolute_hours: int = 24
    session_cookie_secure: bool = False  # Development only; production validates HTTPS below.
    settings_encryption_key: str = ""
    # R05: production secret values are projected into private Linux files by
    # the approved deployment secret provider (not exposed as inline env values).
    database_url_file: str = ""
    jwt_secret_file: str = ""
    settings_encryption_key_file: str = ""
    mail_password_file: str = ""
    resend_webhook_secret_file: str = ""

    frontend_base_url: str = (
        "http://localhost:3000"
    )

    tenant_invitation_expiry_hours: int = (
        168
    )

    # =====================================================
    # CORS
    # =====================================================

    cors_origins: str = (
        "http://localhost:3000,"
        "http://127.0.0.1:3000"
    )

    # Explicit production Host allowlist: external public hostname plus private
    # API DNS hostname(s), with no wildcards. Unused in local development.
    api_trusted_hosts: str = ""

    # R04: upper limits on hosted application gateway, not AAPS ZIP uploads.
    runtime_gateway_request_max_mb: int = 32
    runtime_gateway_response_max_mb: int = 64
    runtime_gateway_socket_timeout_seconds: int = 20

    # =====================================================
    # PYDANTIC SETTINGS
    # =====================================================

    @model_validator(mode="before")
    @classmethod
    def _resolve_r05_secrets(cls, values):
        if str(values.get("app_env", "development")).strip().lower() not in ("prod", "production"):
            return values
        # Never allow an implicit local .env value to replace a managed secret.
        required = (
            ("database_url", "database_url_file", "database"),
            ("jwt_secret", "jwt_secret_file", "jwt"),
            ("settings_encryption_key", "settings_encryption_key_file", "settings"),
        )
        optional = (
            ("mail_password", "mail_password_file", "smtp"),
            ("resend_webhook_secret", "resend_webhook_secret_file", "webhook"),
        )
        resolved = dict(values)
        for target, file_name, purpose in (*required, *optional):
            if str(resolved.get(target) or "").strip():
                raise RuntimeError("R05_PRODUCTION_INLINE_SECRET_DENIED")
            path = str(resolved.get(file_name) or "").strip()
            if not path:
                if (target, file_name, purpose) in required:
                    raise RuntimeError("R05_PRODUCTION_SECRET_FILE_REQUIRED")
                continue
            resolved[target] = read_production_secret_file(path, purpose=purpose)
        return resolved

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =====================================================
    # PACKAGE STORAGE
    # =====================================================

    @property
    def package_storage_root(self) -> Path:

        return Path(
            self.package_storage_path
        ).resolve()

    # =====================================================
    # CORS ORIGIN LIST
    # =====================================================

    @property
    def cors_origin_list(self) -> list[str]:

        return [
            item.strip()
            for item in self.cors_origins.split(",")
            if item.strip()
        ]

    @property
    def api_trusted_host_list(self) -> list[str]:
        return [item.strip().lower() for item in self.api_trusted_hosts.split(",") if item.strip()]

    # =====================================================
    # EMAIL / INVITATION DELIVERY
    # =====================================================

    mail_enabled: bool = False

    mail_host: str = ""
    mail_port: int = 587

    mail_username: str = ""
    mail_password: str = ""

    mail_from_email: str = "no-reply@augmis.com"
    mail_from_name: str = "AUGMIS"

    mail_use_starttls: bool = True
    mail_use_ssl: bool = False

    mail_timeout_seconds: int = 20
    resend_webhook_secret: str = ""


settings = Settings()

# R01: validate deploy-time ingress choices before permitting production startup.
# This does not lift the separate C1-D4 production release gate.
def _dns_hostname(value: str) -> bool:
    if not value or len(value) > 253 or value.endswith("."):
        return False
    try:
        ipaddress.ip_address(value)
        return False  # Require managed DNS, not direct IP exposure.
    except ValueError:
        pass
    return all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
               for label in value.split("."))


def validate_production_ingress_config(config: Settings) -> tuple[str, list[str]]:
    """Return canonical public origin and allowed Hosts; reject unsafe prod config."""
    env = str(config.app_env).strip().lower()
    if env not in ("dev", "development", "prod", "production"):
        raise RuntimeError("C1D42_APP_ENV_UNRECOGNIZED")
    if env in ("dev", "development"):
        return config.frontend_base_url.rstrip("/"), config.api_trusted_host_list

    origin = config.frontend_base_url.strip()
    try:
        parsed = urlsplit(origin)
        hostname = (parsed.hostname or "").lower()
        canonical = f"https://{hostname}"
        if (parsed.scheme != "https" or origin != canonical or parsed.port is not None
                or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment
                or not _dns_hostname(hostname)
                or hostname in ("localhost", "localtest.me")
                or hostname.endswith((".localhost", ".local", ".localtest.me", ".test", ".invalid"))):
            raise ValueError("bad production origin")
    except (ValueError, TypeError) as exc:
        raise RuntimeError("R01_PUBLIC_ORIGIN_INVALID") from exc

    if config.cors_origin_list != [origin]:
        raise RuntimeError("R01_PRODUCTION_CORS_MUST_MATCH_PUBLIC_ORIGIN")
    if not config.session_cookie_secure:
        raise RuntimeError("R01_PRODUCTION_SECURE_COOKIE_REQUIRED")

    hosts = config.api_trusted_host_list
    if (not hosts or hostname not in hosts
            or any(not _dns_hostname(host) or host in ("localhost", "localtest.me")
                   or host.endswith((".localhost", ".localtest.me", ".test", ".invalid"))
                   for host in hosts)):
        raise RuntimeError("R01_API_TRUSTED_HOSTS_INVALID")
    return origin, hosts
