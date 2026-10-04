# services/api/app/schemas/platform_settings.py
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class PlatformEmailSettingsResponse(BaseModel):
    provider: str
    enabled: bool
    host: str
    port: int
    username: str
    credential_configured: bool = Field(alias="credentialConfigured")
    from_email: str = Field(alias="fromEmail")
    from_name: str = Field(alias="fromName")
    use_starttls: bool = Field(alias="useStarttls")
    use_ssl: bool = Field(alias="useSsl")
    timeout_seconds: int = Field(alias="timeoutSeconds")
    source: str
    updated_at: datetime | None = Field(default=None, alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


class PlatformEmailSettingsUpdate(BaseModel):
    provider: str = Field(min_length=1, max_length=30)
    enabled: bool
    host: str = Field(max_length=255)
    port: int = Field(ge=1, le=65535)
    username: str = Field(default="", max_length=320)
    credential: str | None = Field(default=None, max_length=2000)
    clear_credential: bool = Field(default=False, alias="clearCredential")
    from_email: EmailStr = Field(alias="fromEmail")
    from_name: str = Field(alias="fromName", min_length=1, max_length=200)
    use_starttls: bool = Field(alias="useStarttls")
    use_ssl: bool = Field(alias="useSsl")
    timeout_seconds: int = Field(alias="timeoutSeconds", ge=1, le=120)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class PlatformEmailTestRequest(BaseModel):
    recipient: EmailStr
    model_config = ConfigDict(extra="forbid")


class PlatformEmailTestResponse(BaseModel):
    status: str
    recipient: str
    provider: str
    source: str
