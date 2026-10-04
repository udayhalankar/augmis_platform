# services/api/app/schemas/tenant_user.py

from datetime import datetime
import uuid

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
)


class TenantUserAddRequest(BaseModel):

    email: EmailStr

    role_codes: list[str] = Field(
        alias="roleCodes",
        min_length=1,
    )

    model_config = ConfigDict(
        populate_by_name=True,
    )


class TenantUserRoleUpdateRequest(BaseModel):

    role_codes: list[str] = Field(
        alias="roleCodes",
        min_length=1,
    )

    model_config = ConfigDict(
        populate_by_name=True,
    )


class TenantRoleResponse(BaseModel):

    id: uuid.UUID

    code: str

    name: str


class TenantUserIdentityResponse(BaseModel):

    id: uuid.UUID

    email: str

    first_name: str = Field(
        alias="firstName",
    )

    last_name: str = Field(
        alias="lastName",
    )

    status: str

    model_config = ConfigDict(
        populate_by_name=True,
    )


class TenantUserMembershipResponse(BaseModel):

    membership_id: uuid.UUID = Field(
        alias="membershipId",
    )

    status: str

    created_at: datetime = Field(
        alias="createdAt",
    )

    user: TenantUserIdentityResponse

    roles: list[TenantRoleResponse]

    model_config = ConfigDict(
        populate_by_name=True,
    )
