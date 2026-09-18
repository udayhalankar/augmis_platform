import uuid

from pydantic import BaseModel


class InstanceDeployRequest(BaseModel):

    name: str | None = None


class InstanceUpgradeRequest(BaseModel):

    target_version_id: uuid.UUID