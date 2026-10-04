# services/api/app/schemas/invitation.py

import uuid
from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
)


class TenantInvitationCreate(BaseModel):
    email: EmailStr

    role_codes: list[str] = Field(
        alias="roleCodes",
        min_length=1,
        max_length=10,
    )

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
    )


class TenantInvitationRoleResponse(
    BaseModel
):
    id: uuid.UUID
    code: str
    name: str

    model_config = ConfigDict(
        populate_by_name=True
    )


class TenantInvitationTenantResponse(
    BaseModel
):
    id: uuid.UUID
    name: str
    slug: str

    model_config = ConfigDict(
        populate_by_name=True
    )


class TenantInvitationUserResponse(
    BaseModel
):
    id: uuid.UUID
    email: str

    first_name: str = Field(
        alias="firstName"
    )

    last_name: str = Field(
        alias="lastName"
    )

    status: str

    model_config = ConfigDict(
        populate_by_name=True
    )


class TenantInvitationResponse(
    BaseModel
):
    invitation_id: uuid.UUID = Field(
        alias="invitationId"
    )

    email: str

    status: str

    delivery_status: str = Field(
        default="not_attempted",
        alias="deliveryStatus",
    )

    delivery_attempts: int = Field(
        default=0,
        alias="deliveryAttempts",
        ge=0,
    )

    last_sent_at: datetime | None = Field(
        default=None,
        alias="lastSentAt",
    )

    last_delivery_error: str | None = Field(
        default=None,
        alias="lastDeliveryError",
    )

    created_at: datetime = Field(
        alias="createdAt"
    )

    expires_at: datetime = Field(
        alias="expiresAt"
    )

    accepted_at: datetime | None = Field(
        default=None,
        alias="acceptedAt",
    )

    revoked_at: datetime | None = Field(
        default=None,
        alias="revokedAt",
    )

    invited_by_user_id: uuid.UUID | None = Field(
        default=None,
        alias="invitedByUserId",
    )

    accepted_by_user_id: uuid.UUID | None = Field(
        default=None,
        alias="acceptedByUserId",
    )

    existing_user: bool = Field(
        alias="existingUser"
    )

    roles: list[
        TenantInvitationRoleResponse
    ]

    model_config = ConfigDict(
        populate_by_name=True
    )


class TenantInvitationCreateResponse(
    TenantInvitationResponse
):
    invitation_token: str | None = Field(
        default=None,
        alias="invitationToken",
    )

    acceptance_url: str | None = Field(
        default=None,
        alias="acceptanceUrl",
    )


class TenantInvitationResolveResponse(
    BaseModel
):
    invitation_id: uuid.UUID = Field(
        alias="invitationId"
    )

    email: str

    status: str

    expires_at: datetime = Field(
        alias="expiresAt"
    )

    existing_user: bool = Field(
        alias="existingUser"
    )

    can_accept: bool = Field(
        alias="canAccept"
    )

    tenant: (
        TenantInvitationTenantResponse
    )

    roles: list[
        TenantInvitationRoleResponse
    ]

    model_config = ConfigDict(
        populate_by_name=True
    )


class TenantInvitationAcceptExistingRequest(
    BaseModel
):
    token: str = Field(
        min_length=20,
        max_length=500,
    )

    model_config = ConfigDict(
        extra="forbid"
    )


class TenantInvitationAcceptNewRequest(
    BaseModel
):
    token: str = Field(
        min_length=20,
        max_length=500,
    )

    password: str = Field(
        min_length=10,
        max_length=128,
    )

    first_name: str = Field(
        alias="firstName",
        min_length=1,
        max_length=100,
    )

    last_name: str = Field(
        alias="lastName",
        min_length=1,
        max_length=100,
    )

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
    )


class TenantInvitationAcceptanceResponse(
    BaseModel
):
    status: str

    invitation_id: uuid.UUID = Field(
        alias="invitationId"
    )

    membership_id: uuid.UUID = Field(
        alias="membershipId"
    )

    tenant: (
        TenantInvitationTenantResponse
    )

    user: TenantInvitationUserResponse

    roles: list[
        TenantInvitationRoleResponse
    ]

    access_token: str | None = Field(
        default=None,
        alias="accessToken",
    )

    token_type: str | None = Field(
        default=None,
        alias="tokenType",
    )

    model_config = ConfigDict(
        populate_by_name=True
    )