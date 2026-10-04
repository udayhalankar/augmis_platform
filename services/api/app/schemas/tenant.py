# services/api/app/schemas/tenant.py
import uuid

from pydantic import BaseModel, ConfigDict


class TenantCreate(BaseModel):

    name: str

    slug: str


class TenantResponse(BaseModel):

    id: uuid.UUID

    name: str

    slug: str

    status: str

    model_config = ConfigDict(
        from_attributes=True
    )