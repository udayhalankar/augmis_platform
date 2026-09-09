from pathlib import Path

from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict
)


class Settings(BaseSettings):

    app_name: str = "AUGMIS SaaS Platform"

    app_env: str = "development"

    database_url: str

    package_storage_path: str = "data/packages"

    max_upload_size_mb: int = 250

    jwt_secret: str

    jwt_algorithm: str = "HS256"

    access_token_minutes: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    @property
    def package_storage_root(self) -> Path:

        return Path(
            self.package_storage_path
        ).resolve()


settings = Settings()