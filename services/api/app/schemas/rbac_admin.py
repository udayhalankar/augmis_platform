# services/api/app/schemas/rbac_admin.py

from __future__ import annotations

import uuid

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


class RbacPermissionResponse(
    BaseModel
):

    id: uuid.UUID

    code: str

    name: str

    scope_type: str = Field(
        alias="scopeType"
    )

    model_config = ConfigDict(
        populate_by_name=True
    )


class RbacRoleResponse(
    BaseModel
):

    id: uuid.UUID

    scope_type: str = Field(
        alias="scopeType"
    )

    code: str

    name: str

    protected: bool

    permissions: list[
        RbacPermissionResponse
    ]

    model_config = ConfigDict(
        populate_by_name=True
    )


class RbacRolePermissionUpdateRequest(
    BaseModel
):

    permission_codes: list[str] = Field(
        alias="permissionCodes",
        min_length=1,
        max_length=100,
    )

    model_config = ConfigDict(
        populate_by_name=True
    )


class EffectivePermissionResponse(
    BaseModel
):

    scope_type: str = Field(
        alias="scopeType"
    )

    permissions: list[str]

    model_config = ConfigDict(
        populate_by_name=True
    )