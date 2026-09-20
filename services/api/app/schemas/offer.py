import uuid

from pydantic import (
    BaseModel,
    Field,
)


class OfferEntitlementCreate(BaseModel):

    code: str = Field(
        min_length=1,
        max_length=150,
    )

    value: dict | None = None


class OfferCreate(BaseModel):

    offer_key: str = Field(
        min_length=2,
        max_length=100,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    )

    name: str = Field(
        min_length=2,
        max_length=200,
    )

    description: str | None = None

    delivery_type: str = "hosted_dedicated"

    entitlements: list[OfferEntitlementCreate]

class OfferUpdate(BaseModel):

    name: str | None = Field(
        default=None,
        min_length=2,
        max_length=200,
    )

    # None is allowed intentionally so a publisher
    # can clear an existing description.
    description: str | None = None

    version_policy: str | None = None

    pinned_version_id: uuid.UUID | None = None

    auto_upgrade: bool | None = None

    # When supplied, this replaces the complete
    # entitlement template of the draft offer.
    entitlements: list[
        OfferEntitlementCreate
    ] | None = None