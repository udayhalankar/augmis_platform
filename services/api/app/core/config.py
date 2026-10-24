from pathlib import Path

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

    # =====================================================
    # PYDANTIC SETTINGS
    # =====================================================

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