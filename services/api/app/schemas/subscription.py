from pydantic import (
    BaseModel,
    Field,
)


class SubscriptionCreate(BaseModel):
    pass


class SubscriptionSuspendRequest(BaseModel):

    reason: str | None = Field(
        default=None,
        max_length=500,
    )