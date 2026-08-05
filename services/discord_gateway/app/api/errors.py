from typing import Any


class EngineError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        fields: dict[str, Any] | None = None,
        request_id: str | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.fields = fields or {}
        self.request_id = request_id


ERROR_MESSAGES = {
    "DISCORD_LINK_REQUIRED": "Link Twitch first with `/fish link`.",
    "GUILD_BINDING_REQUIRED": "This server is not configured. Use `/fish setup bind`.",
    "TWITCH_OWNER_REQUIRED": "Only the Twitch channel owner can manage these settings.",
    "PERMISSION_DENIED": "You do not have permission to perform this operation.",
    "VALIDATION_ERROR": "Check the entered values.",
    "CONFIG_VERSION_CONFLICT": "Another administrator changed the settings. Open the form again.",
    "LOCATION_NOT_FOUND": "Location not found.",
    "LOCATION_IN_USE": "This location is in use and cannot be deleted.",
    "REWARD_NOT_FOUND": "Reward not found.",
    "LEGACY_IMPORT_INVALID": "The legacy reward file is invalid.",
    "REWARD_ID_CONFLICT": "An imported reward ID already exists.",
    "EVENT_NOT_FOUND": "Event not found.",
    "EVENT_ALREADY_ACTIVE": "Another event is already active.",
    "IDEMPOTENCY_CONFLICT": "This operation was already submitted with different data.",
    "ENGINE_UNAVAILABLE": "The game service is temporarily unavailable. No settings were changed.",
    "ITEM_NOT_FOUND": "Item not found in this channel.",
    "ITEM_DROP_NOT_FOUND": "This item drop does not exist for the location.",
    "ITEM_VERSION_CONFLICT": "Another administrator changed this item. Open the form again.",
    "ITEM_INVALID_EFFECT": "One of the item effects is invalid.",
    "INVENTORY_ITEM_NOT_FOUND": "Inventory item not found.",
    "INVENTORY_FULL": "The viewer inventory is full.",
    "INVENTORY_CAPACITY_CONFLICT": "Inventory capacity prevents this change.",
    "ITEM_COMPATIBILITY": "The effect is not compatible with this item type.",
    "PLAYER_NOT_FOUND": "Viewer not found.",
    "PLAYER_MODIFIER_NOT_FOUND": "Player modifier not found.",
    "EVENT_REQUIRES_REVIEW": "This event has unsafe inherited modifiers and must be reviewed before it can be started.",
}


def localize_error(error: EngineError) -> str:
    base = ERROR_MESSAGES.get(error.code, error.message or "The operation could not be completed.")
    request_id = error.request_id or "unknown"
    return f"{base}\nRequest ID: `{request_id}`"
