from enum import Enum


class ActionType(str, Enum):
    NOTHING = "nothing"
    BASE_MESSAGE = "base_message"
    FISH = "fish"
    POINTS = "points"
    TIMEOUT = "timeout"
    ITEM = "item"
    ADD_MASS = "add_mass"
    ADD_PERCENTAGE_MASS = "add_percentage_mass"
    LEVEL_UP = "level_up"
    ROBBERY = "robbery"
    RUSSIAN_ROULETTE = "russian_roulette"
