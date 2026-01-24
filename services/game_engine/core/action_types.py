from enum import Enum

class ActionType(str, Enum):
    # Basic
    NOTHING = "nothing"
    BASE_MESSAGE = "base_message"
    FISH = "fish"
    
    # External Economy
    POINTS = "points"
    PERCENTAGE_POINTS = "percentage_points"
    
    # Punishment/Role
    TIMEOUT = "timeout"
    UPDATE_ROLE = "update_role"
    
    # Visuals (Overlay)
    PLAY_SOUND = "play_sound"
    TRIGGER_OVERLAY = "trigger_overlay"
    
    # RPG & Mechanics
    ITEM = "item"
    ADD_MASS = "add_mass"
    ADD_PERCENTAGE_MASS = "add_percentage_mass"
    LEVEL_UP = "level_up"
    APPLY_EFFECT = "apply_effect"
    QUEST_UPDATE = "quest_update"
    UNLOCK_LOCATION = "unlock_location"
    
    # Interaction
    ROBBERY = "robbery"
    RUSSIAN_ROULETTE = "russian_roulette"
    DUEL = "duel"
    QTE = "quick_time_event"