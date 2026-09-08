import uuid

from pydantic import BaseModel, ConfigDict


class PublisherCreate(BaseModel):

    name: str
    slug: str


class PublisherResponse(BaseModel):

    id: uuid.UUID

    name: str

    slug: str

    status: str

    model_config = ConfigDict(
        from_attributes=True
    )