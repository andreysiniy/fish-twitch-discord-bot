from pydantic import BaseModel, Field
from typing import Literal, Union
from domain.schemas.common import RewardType

class BaseAction(BaseModel):
    type: RewardType

class TimeoutAction(BaseAction):
    type: Literal[RewardType.TIMEOUT] = RewardType.TIMEOUT
    duration: int
    reason: str

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

GameAction = Union[TimeoutAction, StreamElementsPointsAction, RobberyAction]