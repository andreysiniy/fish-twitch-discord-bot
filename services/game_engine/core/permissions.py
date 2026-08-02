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
    PLAYERS_READ = "channel.players.read"
    PLAYERS_WRITE = "channel.players.write"


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
        ChannelPermission.PLAYERS_READ,
        ChannelPermission.PLAYERS_WRITE,
    },
    "moderator": {
        ChannelPermission.CONFIG_READ,
        ChannelPermission.EVENTS_TOGGLE,
        ChannelPermission.COOLDOWN_WRITE,
        ChannelPermission.ITEMS_READ,
        ChannelPermission.PLAYERS_READ,
    },
}
