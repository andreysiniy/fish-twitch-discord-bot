"""Compatibility export for the actor-pool public surface."""

try:
    from .twitch_client import ActorClient, ActorPool, ChatMessage
except ImportError:  # pragma: no cover - script-style Docker entrypoint
    from twitch_client import ActorClient, ActorPool, ChatMessage

__all__ = ["ActorClient", "ActorPool", "ChatMessage"]
