from enum import Enum


class ChannelPermission(str, Enum):
    CONFIG_READ = "channel.config.read"
    CONFIG_WRITE = "channel.config.write"
    LOCATIONS_WRITE = "channel.locations.write"
    REWARDS_WRITE = "channel.rewards.write"
    EVENTS_WRITE = "channel.events.write"
    EVENTS_TOGGLE = "channel.events.toggle"
    COOLDOWN_WRITE = "channel.cooldown.write"
    INTEGRATIONS_WRITE = "channel.integrations.write"
    ACCESS_WRITE = "channel.access.write"
    ITEMS_READ = "channel.items.read"
    ITEMS_WRITE = "channel.items.write"
    ITEM_DROPS_WRITE = "channel.item_drops.write"
    PLAYER_INVENTORY_READ = "channel.player_inventory.read"
    PLAYER_ITEMS_GRANT = "channel.player_items.grant"
    PLAYER_MODIFIERS_READ = "channel.player_modifiers.read"
    PLAYER_MODIFIERS_WRITE = "channel.player_modifiers.write"
    CASTS_READ = "channel.casts.read"
    CASTS_TECHNICAL_READ = "channel.casts.technical_read"
    RECONCILIATION_READ = "channel.reconciliation.read"
    RECONCILIATION_WRITE = "channel.reconciliation.write"


ROLE_PERMISSIONS = {
    "owner": set(ChannelPermission),
    "editor": {
        ChannelPermission.CONFIG_READ,
        ChannelPermission.CONFIG_WRITE,
        ChannelPermission.LOCATIONS_WRITE,
        ChannelPermission.REWARDS_WRITE,
        ChannelPermission.EVENTS_WRITE,
        ChannelPermission.EVENTS_TOGGLE,
        ChannelPermission.COOLDOWN_WRITE,
        ChannelPermission.ITEMS_READ,
        ChannelPermission.ITEMS_WRITE,
        ChannelPermission.ITEM_DROPS_WRITE,
        ChannelPermission.CASTS_READ,
        ChannelPermission.CASTS_TECHNICAL_READ,
    },
    "moderator": {
        ChannelPermission.CONFIG_READ,
        ChannelPermission.EVENTS_TOGGLE,
        ChannelPermission.COOLDOWN_WRITE,
        ChannelPermission.ITEMS_READ,
        ChannelPermission.PLAYER_INVENTORY_READ,
        ChannelPermission.CASTS_READ,
    },
}
