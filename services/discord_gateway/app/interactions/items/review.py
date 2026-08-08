"""Item Review screen (wizard spec §38/§39/§40/§63/§64/§65).

``ItemReviewView`` is the final confirmation card before the backend mutation.
It shows a type-aware embed (spec §11.4) where irrelevant mechanics are never
rendered, blocks Confirm on compatibility errors, and lets the admin jump back
to Basic Info / Mechanics / Effects without losing the draft (spec §6/§40).
A failed submit re-renders the review with the error attached and returns the
session to REVIEW so the admin can fix and retry (spec §48/§61).
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import discord

from app.api.errors import EngineError, localize_error
from app.domain.item_effect_registry import describe_effect
from app.domain.item_review import compatibility_issues
from app.domain.item_ui_registry import (
    BREAK_BEHAVIOR_OPTIONS,
    EQUIPMENT_SLOT_LABELS,
    ITEM_TYPE_OPTIONS,
    RARITY_OPTIONS,
)
from app.interactions.metrics import count_wizard_timeout

logger = logging.getLogger("discord.item_review")

CONFIRM_TIMEOUT_SECONDS = 180

ConfirmCallback = Callable[[discord.Interaction], Awaitable[None]]
EditCallback = Callable[[discord.Interaction], Awaitable[None]]


def _type_label(item_type: str) -> str:
    for label, value in ITEM_TYPE_OPTIONS:
        if value == item_type:
            return label
    return item_type.replace("_", " ").title()


def _break_label(value: str) -> str:
    return next((name for name, val in BREAK_BEHAVIOR_OPTIONS if val == value), value)


def _add_effect_fields(embed: discord.Embed, effects: list[dict[str, Any]]) -> None:
    """Render effects as human lines; split into multiple fields on overflow.

    Spec §63: raw JSON is forbidden in previews and long content is split into
    multiple embeds/fields instead of silently truncated.
    """
    if not effects:
        return
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for effect in effects:
        line = f"• {describe_effect(effect)}"
        if size + len(line) + 1 > 1024 and current:
            chunks.append("\n".join(current))
            current = []
            size = 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    for index, chunk in enumerate(chunks):
        name = f"Effects ({len(effects)})" if index == 0 else "Effects (continued)"
        embed.add_field(name=name, value=chunk[:1024], inline=False)


def review_embed(
    draft: dict[str, Any],
    *,
    template_label: str | None = None,
    schema_version: int | None = None,
    version: int | None = None,
    extra_errors: list[str] | None = None,
) -> discord.Embed:
    """Type-aware review card (spec §38/§39/§63). Never renders raw JSON.

    Irrelevant mechanics are hidden per spec §11.4: equipment shows
    slot/durability/break behavior, everything else shows stack size. Backend
    submit errors are appended to the blocking-errors field via ``extra_errors``
    but do not change the draft-level blocking state (spec §48).
    """
    errors, warnings = compatibility_issues(draft)
    errors = errors + list(extra_errors or [])
    item_type = str(draft.get("item_type") or "material")
    title = str(draft.get("title") or draft.get("item_id") or "Item")
    rarity = next(
        (label for label, value in RARITY_OPTIONS if value == draft.get("rarity")),
        str(draft.get("rarity") or "?"),
    )
    embed = discord.Embed(
        title="Review Item",
        description=f"**{title}**\n{rarity} {_type_label(item_type)}",
        color=discord.Color.gold(),  # Review / unsaved → gold (spec §64)
    )
    embed.add_field(name="Stable ID", value=f"`{draft.get('item_id') or '?'}`", inline=True)
    if template_label:
        embed.add_field(name="Template", value=template_label, inline=True)
    embed.add_field(name="Rarity", value=rarity, inline=True)
    if item_type == "equipment":
        slot = draft.get("equipment_slot")
        embed.add_field(
            name="Equipment Slot",
            value=EQUIPMENT_SLOT_LABELS.get(slot, slot or "Not set"),
            inline=True,
        )
        break_policy = str(draft.get("break_policy") or "indestructible")
        embed.add_field(name="Break Behavior", value=_break_label(break_policy), inline=True)
        durability = draft.get("max_durability")
        embed.add_field(
            name="Durability",
            value=str(durability) if durability else "Not used",
            inline=True,
        )
    else:
        embed.add_field(name="Stack Size", value=str(draft.get("stack_size", 1)), inline=True)
    description = draft.get("description")
    if description:
        embed.add_field(name="Description", value=str(description)[:1024], inline=False)
    _add_effect_fields(embed, list(draft.get("effects") or []))
    if errors:
        embed.add_field(
            name="Blocking errors",
            value="\n".join(f"⛔ {error}" for error in errors)[:1024],
            inline=False,
        )
    if warnings:
        embed.add_field(
            name="Warnings",
            value="\n".join(f"⚠️ {warning}" for warning in warnings)[:1024],
            inline=False,
        )
    elif not errors:
        embed.add_field(
            name="Warnings", value="• No blocking validation errors found.", inline=False
        )
    footer: list[str] = []
    if version is not None:
        footer.append(f"version {version}")
    if schema_version is not None:
        footer.append(f"schema {schema_version}")
    footer.append(f"{len(draft.get('effects') or [])} effect(s)")
    embed.set_footer(text=" · ".join(footer))
    return embed


class ItemReviewView(discord.ui.View):
    """Final review card with edit-back navigation (spec §38/§40).

    Confirm is only enabled when the draft has no blocking compatibility errors.
    A failed submit re-renders the card with the error and keeps the controls
    usable so the admin can fix the draft and retry (spec §48/§61).
    """

    def __init__(
        self,
        *,
        initiator_id: int,
        draft: dict[str, Any],
        confirm_label: str,
        on_confirm: ConfirmCallback,
        on_edit_basic: EditCallback,
        on_edit_mechanics: EditCallback,
        on_edit_effects: EditCallback,
        on_cancel: EditCallback,
        template_label: str | None = None,
        schema_version: int | None = None,
        version: int | None = None,
        timeout: int = 600,
        restart_text: str = "Run /fish item create again.",
    ):
        super().__init__(timeout=timeout)
        self.initiator_id = initiator_id
        self.draft = draft
        self.template_label = template_label
        self.schema_version = schema_version
        self.version = version
        self.on_confirm = on_confirm
        self.on_edit_basic = on_edit_basic
        self.on_edit_mechanics = on_edit_mechanics
        self.on_edit_effects = on_edit_effects
        self.on_cancel = on_cancel
        self._restart_text = restart_text
        self._extra_errors: list[str] = []
        self._confirming = False
        self.confirm.label = confirm_label
        self._sync_confirm_state()

    # --- state --------------------------------------------------------------

    def _blocking_errors(self) -> list[str]:
        errors, _ = compatibility_issues(self.draft)
        return errors

    def _sync_confirm_state(self) -> None:
        self.confirm.disabled = bool(self._blocking_errors())

    def embed(self) -> discord.Embed:
        return review_embed(
            self.draft,
            template_label=self.template_label,
            schema_version=self.schema_version,
            version=self.version,
            extra_errors=self._extra_errors,
        )

    # --- owner guard -----------------------------------------------------------

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.initiator_id:
            await interaction.response.send_message(
                "These controls belong to another user.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        count_wizard_timeout("item_review")
        if self.message is not None:
            await self.message.edit(
                content=f"⏱ The item review expired. {self._restart_text}",
                view=self,
            )
        self.stop()

    # --- confirm ---------------------------------------------------------------

    @discord.ui.button(label="Create Item", style=discord.ButtonStyle.success, row=0)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        # Spec §61: disable controls first so a double click never issues two
        # HTTP mutations; the session also transitions to SUBMITTING in Redis.
        if self._confirming:
            return
        self._confirming = True
        for item in self.children:
            item.disabled = True
        if not interaction.response.is_done():
            # Buttons may only ack with DEFERRED_MESSAGE_UPDATE (type 6); a
            # thinking defer maps to type 5, which Discord rejects.
            await interaction.response.defer()
        try:
            await self.on_confirm(interaction)
        except (EngineError, ValueError) as error:
            content = localize_error(error) if isinstance(error, EngineError) else str(error)
            await self._report_failure(interaction, content)
        except Exception:
            logger.exception("Item review confirm failed for interaction %s", interaction.id)
            await self._report_failure(interaction, "The operation could not be completed.")

    async def _report_failure(self, interaction: discord.Interaction, content: str) -> None:
        """Return to REVIEW with the error attached (spec §61)."""
        self._extra_errors.append(content)
        self._confirming = False
        for item in self.children:
            item.disabled = False
        self._sync_confirm_state()
        try:
            await interaction.edit_original_response(content=None, embed=self.embed(), view=self)
        except Exception:
            logger.exception("Failed to re-render the item review after a failed submit")

    # --- edit-back navigation (spec §6/§40) --------------------------------------

    @discord.ui.button(label="Edit Basic Info", style=discord.ButtonStyle.secondary, row=1)
    async def edit_basic(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await self.on_edit_basic(interaction)

    @discord.ui.button(label="Edit Mechanics", style=discord.ButtonStyle.secondary, row=1)
    async def edit_mechanics(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        await self.on_edit_mechanics(interaction)

    @discord.ui.button(label="Edit Effects", style=discord.ButtonStyle.secondary, row=1)
    async def edit_effects(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        await self.on_edit_effects(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=0)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await self.on_cancel(interaction)


class VersionConflictView(discord.ui.View):
    """Optimistic-locking conflict recovery (wizard spec §55).

    When the backend rejects an edit with ``ITEM_VERSION_CONFLICT`` the flow is
    kept open: the admin either reloads the latest version (refetching the
    backend item and re-seeding the draft) or cancels. There is never an
    automatic overwrite of the newer definition.
    """

    def __init__(
        self,
        *,
        initiator_id: int,
        on_reload: Callable[[discord.Interaction], Awaitable[None]],
        on_cancel: Callable[[discord.Interaction], Awaitable[None]],
        timeout: int = CONFIRM_TIMEOUT_SECONDS,
    ):
        super().__init__(timeout=timeout)
        self.initiator_id = initiator_id
        self.on_reload = on_reload
        self.on_cancel = on_cancel

    def embed(self) -> discord.Embed:
        # Conflict → red/danger so the admin notices the state was rejected.
        embed = discord.Embed(
            title="Item Changed Elsewhere",
            description=(
                "This item was changed by another administrator while you were "
                "editing it. Reload the latest version to continue, or cancel "
                "the edit."
            ),
            color=discord.Color.red(),
        )
        embed.set_footer(text="Your unsaved draft was not applied.")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.initiator_id:
            await interaction.response.send_message(
                "These controls belong to another user.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        count_wizard_timeout("item_version_conflict")
        if self.message is not None:
            await self.message.edit(
                content="⏱ The edit expired. Run /fish item edit again.",
                view=self,
            )
        self.stop()

    @discord.ui.button(label="Reload Latest Version", style=discord.ButtonStyle.success, row=0)
    async def reload(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await self.on_reload(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=0)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await self.on_cancel(interaction)
