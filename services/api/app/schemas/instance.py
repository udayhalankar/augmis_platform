from pydantic import BaseModel


class InstanceDeployRequest(BaseModel):

    name: str | None = None