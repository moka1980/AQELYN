"""A deliberately permissive signal model for the AC-2 negative control."""

from pydantic import BaseModel, ConfigDict


class PermissiveSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
