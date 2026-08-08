"""Item wizard session and state machine (spec §41/§42/§60).

The whole wizard state lives in Redis as one JSON document. The draft is a
nested object under ``draft``; the outer keys carry the flow metadata:
``flow_id``, ``flow_type``, ``discord_user_id``, ``discord_guild_id``,
``channel_id``, ``step``, ``template`` and ``expected_version``. ``template``
is UI metadata and never reaches the backend payload.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.interactions.sessions import WizardSessionStore


class WizardStep(str, Enum):
    TEMPLATE = "template"
    BASIC_INFO = "basic_info"
    RARITY = "rarity"
    MECHANICS = "mechanics"
    EFFECTS = "effects"
    REVIEW = "review"
    SUBMITTING = "submitting"
    DONE = "done"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


# Explicit allowed transitions (spec §60). Confirm is only reachable from
# REVIEW; every other state must move forward through the wizard.
ALLOWED_TRANSITIONS: dict[WizardStep, frozenset[WizardStep]] = {
    WizardStep.TEMPLATE: frozenset({WizardStep.BASIC_INFO, WizardStep.CANCELLED}),
    WizardStep.BASIC_INFO: frozenset(
        {WizardStep.RARITY, WizardStep.TEMPLATE, WizardStep.CANCELLED}
    ),
    WizardStep.RARITY: frozenset(
        {WizardStep.MECHANICS, WizardStep.BASIC_INFO, WizardStep.CANCELLED}
    ),
    WizardStep.MECHANICS: frozenset({WizardStep.EFFECTS, WizardStep.RARITY, WizardStep.CANCELLED}),
    WizardStep.EFFECTS: frozenset({WizardStep.REVIEW, WizardStep.MECHANICS, WizardStep.CANCELLED}),
    WizardStep.REVIEW: frozenset(
        {
            WizardStep.SUBMITTING,
            WizardStep.BASIC_INFO,
            WizardStep.MECHANICS,
            WizardStep.EFFECTS,
            WizardStep.CANCELLED,
        }
    ),
    WizardStep.SUBMITTING: frozenset({WizardStep.REVIEW, WizardStep.DONE}),
    WizardStep.DONE: frozenset(),
    WizardStep.CANCELLED: frozenset(),
    WizardStep.EXPIRED: frozenset(),
}


def can_transition(current: WizardStep, target: WizardStep) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


@dataclass
class ItemWizardSession:
    store: WizardSessionStore
    flow_id: str
    flow_type: str
    discord_user_id: str
    discord_guild_id: str | None
    channel_id: int | None
    step: WizardStep
    template: str | None = None
    draft: dict[str, Any] = field(default_factory=dict)
    expected_version: int | None = None

    @classmethod
    async def create(
        cls,
        store: WizardSessionStore,
        *,
        flow_type: str,
        discord_user_id: int | str,
        discord_guild_id: int | str | None,
        channel_id: int | None,
        template: str | None = None,
        draft: dict[str, Any] | None = None,
        expected_version: int | None = None,
        step: WizardStep = WizardStep.TEMPLATE,
    ) -> "ItemWizardSession":
        session = cls(
            store=store,
            flow_id="",  # assigned below by the store
            flow_type=flow_type,
            discord_user_id=str(discord_user_id),
            discord_guild_id=str(discord_guild_id) if discord_guild_id else None,
            channel_id=channel_id,
            step=step,
            template=template,
            draft=draft or {},
            expected_version=expected_version,
        )
        flow_id = await store.create(session.discord_user_id, session.to_redis())
        session.flow_id = flow_id
        return session

    @classmethod
    async def load(
        cls, store: WizardSessionStore, user_id: int | str, flow_id: str
    ) -> "ItemWizardSession":
        raw = await store.get(user_id, flow_id)
        if raw is None:
            raise KeyError("Wizard session expired")
        return cls(
            store=store,
            flow_id=raw.get("flow_id") or flow_id,
            flow_type=raw.get("flow_type", "item_create"),
            discord_user_id=str(raw.get("discord_user_id") or user_id),
            discord_guild_id=raw.get("discord_guild_id"),
            channel_id=raw.get("channel_id"),
            step=WizardStep(raw.get("step", WizardStep.TEMPLATE.value)),
            template=raw.get("template"),
            draft=raw.get("draft") or {},
            expected_version=raw.get("expected_version"),
        )

    def to_redis(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id,
            "flow_type": self.flow_type,
            "discord_user_id": self.discord_user_id,
            "discord_guild_id": self.discord_guild_id,
            "channel_id": self.channel_id,
            "step": self.step.value,
            "template": self.template,
            "draft": self.draft,
            "expected_version": self.expected_version,
        }

    async def save(self) -> None:
        await self.store.update(self.discord_user_id, self.flow_id, self.to_redis())

    async def transition(self, target: WizardStep) -> None:
        if not can_transition(self.step, target):
            raise ValueError(f"Cannot move from {self.step.value} to {target.value}")
        self.step = target
        await self.save()

    async def delete(self) -> None:
        await self.store.delete(self.discord_user_id, self.flow_id)

    def apply_template_defaults(self) -> None:
        from app.domain.item_ui_registry import template_to_defaults

        defaults = template_to_defaults(self.template or "material")
        self.draft.update(defaults)
