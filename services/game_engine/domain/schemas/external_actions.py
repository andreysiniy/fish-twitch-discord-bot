from typing import Literal

from pydantic import BaseModel, Field


class ExternalActionRequest(BaseModel):
    action_type: Literal["points"]
    channel_id: str = Field(..., min_length=1)
    target_username: str = Field(..., min_length=1)
    amount: int


class ExternalActionResponse(BaseModel):
    status: Literal["queued", "completed"]
    operation_id: str
