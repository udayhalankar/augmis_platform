from pydantic import (
    BaseModel,
    Field,
)

import uuid

class SubscriptionCreate(BaseModel):
    pass


class SubscriptionSuspendRequest(BaseModel):

    reason: str | None = Field(
        default=None,
        max_length=500,
    )

class SubscriptionChangeOfferRequest(BaseModel):

    offer_id: uuid.UUID

class SubscriptionPromoteBaselineRequest(BaseModel):
    target_version_id: uuid.UUID

