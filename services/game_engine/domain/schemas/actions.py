from pydantic import BaseModel, Field
from typing import Literal, Union, Optional, Any
from domain.schemas.common import RewardType

class BaseAction(BaseModel):
    type: RewardType
    action_message: Optional[str] = None

class TimeoutAction(BaseAction):
    type: Literal[RewardType.TIMEOUT] = RewardType.TIMEOUT
    duration: int
    reason: str
    target_user: str

class StreamElementsPointsAction(BaseAction):
    """Добавить/Снять очки"""
    type: Literal[RewardType.POINTS] = RewardType.POINTS
    amount: int
    target_user: str | None = None

class RobberyAction(BaseAction):
    """Ограбление через SE"""
    type: Literal[RewardType.ROBBERY] = RewardType.ROBBERY
    attacker_id: str
    victim_scope: str = "active" # active, random, top
    steal_percent: float

class RussianRouletteAction(BaseAction):
    type: Literal[RewardType.RUSSIAN_ROULETTE] = RewardType.RUSSIAN_ROULETTE
    hit: bool
    penalty_action: Optional[Any] = None

class AddMassAction(BaseAction):
    """Событие добавления массы (кг)"""
    type: Literal["add_mass"] = "add_mass"
    amount: float
    amount_now: float
    total_mass: float

class SendBaseMessageAction(BaseAction):
    """Просто отправить сообщение в чат"""
    type: Literal["base_message"] = "base_message"

GameAction = Union[TimeoutAction, StreamElementsPointsAction, RobberyAction, RussianRouletteAction, AddMassAction, SendBaseMessageAction]