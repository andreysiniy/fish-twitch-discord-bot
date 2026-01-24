from pydantic import BaseModel, Field
from typing import Literal, Union, Optional, Any
from core.action_types import ActionType 

class BaseAction(BaseModel):
    type: ActionType
    action_message: Optional[str] = None

class TimeoutAction(BaseAction):
    type: Literal[ActionType.TIMEOUT] = ActionType.TIMEOUT
    duration: int
    reason: str
    target_user: str

class StreamElementsPointsAction(BaseAction):
    """Добавить/Снять очки"""
    type: Literal[ActionType.POINTS] = ActionType.POINTS
    amount: int
    target_user: str | None = None

class RobberyAction(BaseAction):
    """Ограбление через SE"""
    type: Literal[ActionType.ROBBERY] = ActionType.ROBBERY
    attacker_id: str
    victim_scope: str = "active" # active, random, top
    steal_percent: float

class RussianRouletteAction(BaseAction):
    type: Literal[ActionType.RUSSIAN_ROULETTE] = ActionType.RUSSIAN_ROULETTE
    hit: bool
    penalty_action: Optional[Any] = None

class AddMassAction(BaseAction):
    """Событие добавления массы (кг)"""
    type: Literal[ActionType.ADD_MASS] = ActionType.ADD_MASS
    amount: float
    amount_now: float
    total_mass: float

class SendBaseMessageAction(BaseAction):
    """Просто отправить сообщение в чат"""
    type: Literal[ActionType.BASE_MESSAGE] = ActionType.BASE_MESSAGE

class AddItemAction(BaseAction):
    """Добавить предмет в инвентарь"""
    type: Literal[ActionType.ITEM] = ActionType.ITEM
    item_id: str
    item_name: str
    quantity: int = 1

class LevelUpAction(BaseAction):
    """Повышение уровня пользователя"""
    type: Literal[ActionType.LEVEL_UP] = ActionType.LEVEL_UP
    new_level: int
 
GameAction = Union[TimeoutAction, StreamElementsPointsAction, RobberyAction, RussianRouletteAction, AddMassAction, SendBaseMessageAction, AddItemAction, LevelUpAction]