"""Publisher membership administration HTTP payloads."""
from pydantic import BaseModel, Field


class PublisherUserAddRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    roleCodes: list[str] = Field(min_length=1, max_length=3)


class PublisherUserRoleUpdateRequest(BaseModel):
    roleCodes: list[str] = Field(min_length=1, max_length=3)
