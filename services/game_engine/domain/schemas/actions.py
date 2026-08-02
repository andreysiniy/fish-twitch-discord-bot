from decimal import Decimal
from typing import Literal, Optional, Union

from core.action_types import ActionType
from pydantic import BaseModel


class BaseAction(BaseModel):
    type: ActionType
    action_message: Optional[str] = None


class TimeoutAction(BaseAction):
    type: Literal[ActionType.TIMEOUT] = ActionType.TIMEOUT
    duration: int
    reason: str
    target_user: str


class StreamElementsPointsAction(BaseAction):
    type: Literal[ActionType.POINTS] = ActionType.POINTS
    amount: int
    target_user: str | None = None


class AddMassAction(BaseAction):
    type: Literal[ActionType.ADD_MASS] = ActionType.ADD_MASS
    amount: Decimal
    amount_now: Decimal
    total_mass: Decimal


class SendBaseMessageAction(BaseAction):
    type: Literal[ActionType.BASE_MESSAGE] = ActionType.BASE_MESSAGE


class AddItemAction(BaseAction):
    type: Literal[ActionType.ITEM] = ActionType.ITEM
    item_id: str
    item_name: str
    quantity: int = 1


class LevelUpAction(BaseAction):
    type: Literal[ActionType.LEVEL_UP] = ActionType.LEVEL_UP
    new_level: int


class DupeAction(BaseAction):
    type: Literal[ActionType.DUPE] = ActionType.DUPE
    amount: int
    delay: int = 0


GameAction = Union[
    TimeoutAction,
    StreamElementsPointsAction,
    AddMassAction,
    SendBaseMessageAction,
    AddItemAction,
    LevelUpAction,
    DupeAction,
]
