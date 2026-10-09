import uuid

from pydantic import BaseModel, ConfigDict, Field


class PublisherCreate(BaseModel):

    name: str
    slug: str

    # Required for every newly-created publisher workspace.
    tenantId: uuid.UUID

    # Optional; must be an active Tenant Owner in that organization.
    initialOwnerEmail: str | None = None


class PublisherResponse(BaseModel):

    id: uuid.UUID

    name: str

    slug: str

    status: str

    # Legacy publishers remain unassigned until reviewed.
    tenantId: uuid.UUID | None = Field(default=None, validation_alias="tenant_id")

    model_config = ConfigDict(
        from_attributes=True
    )

class PublisherOrganizationAssign(BaseModel):
    tenantId: uuid.UUID
