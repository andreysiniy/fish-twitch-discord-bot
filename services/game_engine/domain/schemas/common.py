from enum import Enum

class RewardType(str, Enum):
    NOTHING = "nothing"
    POINTS = "points"
    ITEM = "item"
    TIMEOUT = "timeout"
    RUSSIAN_ROULETTE = "russian_roulette"
    ROBBERY = "robbery"   

class Rarity(str, Enum):
    COMMON = "common"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"