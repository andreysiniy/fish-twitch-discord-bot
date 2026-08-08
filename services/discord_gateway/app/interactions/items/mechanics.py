"""Item Mechanics step (spec §11).

Type-aware controls: equipment shows slot/durability/break behavior, everything
else shows stack settings. ``stack_size`` is forced to 1 for equipment and never
shown; consumables and loot boxes never expose durability or slot controls.
"""

from collections.abc import Awaitable, Callable

import discord

from app.domain.item_ui_registry import (
    BREAK_BEHAVIOR_OPTIONS,
    CHARM_SLOT_OPTIONS,
    EQUIPMENT_SLOT_LABELS,
)
from app.interactions.metrics import count_wizard_timeout

PersistCallback = Callable[[discord.Interaction], Awaitable[None]]
ContinueCallback = Callable[[discord.Interaction], Awaitable[None]]
BackCallback = Callable[[discord.Interaction], Awaitable[None]]
CancelCallback = Callable[[discord.Interaction], Awaitable[None]]


def _break_label(value: str) -> str:
    return next((name for name, val in BREAK_BEHAVIOR_OPTIONS if val == value), value)


def _slot_label(value: str | None) -> str:
    if not value:
        return "Not set"
    return EQUIPMENT_SLOT_LABELS.get(value, value)


def mechanics_embed(draft: dict) -> discord.Embed:
    item_type = draft.get("item_type", "material")
    embed = discord.Embed(
        title="Item Mechanics",
        color=discord.Color.blurple(),
    )
    if item_type == "equipment":
        slot = draft.get("equipment_slot")
        embed.add_field(name="Equipment Slot", value=_slot_label(slot), inline=True)
        break_policy = draft.get("break_policy", "indestructible")
        embed.add_field(name="Break Behavior", value=_break_label(break_policy), inline=True)
        durability = draft.get("max_durability")
        embed.add_field(
            name="Durability",
            value=f"{durability}" if durability else "Not used",
            inline=True,
        )
        if break_policy != "indestructible" and not durability:
            embed.add_field(
                name="Required",
                value="Set a maximum durability for the selected break behavior.",
                inline=False,
            )
    else:
        embed.add_field(
            name="Maximum Stack Size",
            value=str(draft.get("stack_size", 1)),
            inline=True,
        )
    embed.set_footer(text="Type-aware: irrelevant mechanics are never shown.")
    return embed


class DurabilityModal(discord.ui.Modal):
    """Maximum durability for a breakable equipment item (spec §11.2)."""

    def __init__(
        self,
        on_saved: Callable[[discord.Interaction, int], Awaitable[None]],
        *,
        current: int | None = None,
    ):
        super().__init__(title="Durability")
        self.on_saved = on_saved
        self.max_durability = discord.ui.TextInput(
            label="Maximum Durability",
            max_length=7,
            required=True,
            default=str(current) if current else "",
            placeholder="150",
        )
        self.add_item(self.max_durability)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = self.max_durability.value.strip()
        try:
            value = int(raw)
        except ValueError:
            await interaction.response.send_message(
                "Maximum durability must be a whole number.", ephemeral=True
            )
            return
        if not 1 <= value <= 1_000_000:
            await interaction.response.send_message(
                "Maximum durability must be 1..1000000.", ephemeral=True
            )
            return
        await self.on_saved(interaction, value)


class StackSettingsModal(discord.ui.Modal):
    """Maximum stack size for a non-equipment item (spec §11.3)."""

    def __init__(
        self,
        on_saved: Callable[[discord.Interaction, int], Awaitable[None]],
        *,
        current: int | None = None,
    ):
        super().__init__(title="Stack Settings")
        self.on_saved = on_saved
        self.max_stack = discord.ui.TextInput(
            label="Maximum Stack Size",
            max_length=7,
            required=True,
            default=str(current) if current else "20",
            placeholder="20",
        )
        self.add_item(self.max_stack)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = self.max_stack.value.strip()
        try:
            value = int(raw)
        except ValueError:
            await interaction.response.send_message(
                "Maximum stack size must be a whole number.", ephemeral=True
            )
            return
        if not 1 <= value <= 1_000_000:
            await interaction.response.send_message(
                "Maximum stack size must be 1..1000000.", ephemeral=True
            )
            return
        await self.on_saved(interaction, value)


class MechanicsView(discord.ui.View):
    """Step 4: type-aware item mechanics (spec §11).

    The view mutates ``draft`` in place, then calls ``on_persist`` so the
    orchestrator saves the draft to Redis and re-renders the message. This
    keeps the flow single-source: the draft never lives only in the view.
    """

    def __init__(
        self,
        *,
        initiator_id: int,
        template: str,
        draft: dict,
        on_persist: PersistCallback,
        on_continue: ContinueCallback,
        on_back: BackCallback,
        on_cancel: CancelCallback,
        timeout: int = 600,
        restart_text: str = "Run /fish item create again.",
    ):
        super().__init__(timeout=timeout)
        self.initiator_id = initiator_id
        self.template = template
        self.draft = draft
        self.on_persist = on_persist
        self.on_continue = on_continue
        self.on_back = on_back
        self.on_cancel = on_cancel
        self._restart_text = restart_text
        self._configure_controls()
        self._update_state()

    # --- control wiring ------------------------------------------------------

    def _configure_controls(self) -> None:
        item_type = self.draft.get("item_type", "material")
        if item_type == "equipment":
            # Equipment never shows stack controls: stack_size is forced to 1.
            self.remove_item(self.stack_button)
            if self.template == "charm":
                self.slot_select.options = [
                    discord.SelectOption(label=name, value=value)
                    for name, value in CHARM_SLOT_OPTIONS
                ]
            else:
                self.remove_item(self.slot_select)
            self.break_select.options = [
                discord.SelectOption(label=name, value=value)
                for name, value in BREAK_BEHAVIOR_OPTIONS
            ]
        else:
            self.remove_item(self.slot_select)
            self.remove_item(self.break_select)
            self.remove_item(self.durability_button)

    def _update_state(self) -> None:
        item_type = self.draft.get("item_type", "material")
        break_policy = self.draft.get("break_policy", "indestructible")
        if item_type == "equipment":
            if self.template == "charm":
                self.slot_select.disabled = False
            breakable = break_policy != "indestructible"
            durability_set = bool(self.draft.get("max_durability"))
            self.durability_button.disabled = not breakable
            self.durability_button.label = (
                "Set durability"
                if not durability_set
                else f"Edit durability ({self.draft['max_durability']})"
            )
            self.continue_button.disabled = not (break_policy == "indestructible" or durability_set)
            if self.template == "charm" and not self.draft.get("equipment_slot"):
                self.continue_button.disabled = True
        else:
            self.continue_button.disabled = False

    # --- equipment controls ----------------------------------------------------

    @discord.ui.select(placeholder="Charm slot…", min_values=1, max_values=1, row=0)
    async def slot_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        self.draft["equipment_slot"] = select.values[0]
        self._update_state()
        await self.on_persist(interaction)

    @discord.ui.select(placeholder="Break behavior…", min_values=1, max_values=1, row=1)
    async def break_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        policy = select.values[0]
        self.draft["break_policy"] = policy
        if policy == "indestructible":
            self.draft["max_durability"] = None
            self._update_state()
            await self.on_persist(interaction)
            return
        self._update_state()
        if not self.draft.get("max_durability"):
            await interaction.response.send_modal(
                DurabilityModal(self._durability_saved, current=None)
            )
        else:
            await self.on_persist(interaction)

    @discord.ui.button(label="Set durability", style=discord.ButtonStyle.secondary, row=2)
    async def durability_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(
            DurabilityModal(self._durability_saved, current=self.draft.get("max_durability"))
        )

    async def _durability_saved(self, interaction: discord.Interaction, value: int) -> None:
        self.draft["max_durability"] = value
        self._update_state()
        await self.on_persist(interaction)

    # --- stack controls (non-equipment) ----------------------------------------

    @discord.ui.button(label="Set stack size", style=discord.ButtonStyle.secondary, row=2)
    async def stack_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(
            StackSettingsModal(self._stack_saved, current=self.draft.get("stack_size"))
        )

    async def _stack_saved(self, interaction: discord.Interaction, value: int) -> None:
        self.draft["stack_size"] = value
        self._update_state()
        await self.on_persist(interaction)

    # --- navigation -------------------------------------------------------------

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.success, row=3)
    async def continue_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        await self.on_continue(interaction)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=3)
    async def back_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        await self.on_back(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=3)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        await self.on_cancel(interaction)

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
        count_wizard_timeout("item_mechanics")
        if self.message is not None:
            await self.message.edit(
                content=f"⏱ The item mechanics step expired. {self._restart_text}",
                view=self,
            )
        self.stop()


def advanced_item_type_embed() -> discord.Embed:
    return discord.Embed(
        title="Item Type",
        description="The Advanced template lets you pick the backend item type manually.",
        color=discord.Color.blurple(),
    )


# Re-export for the orchestrator; keeps this module the only place that knows
# the mechanics vocabulary.
__all__ = [
    "MechanicsView",
    "DurabilityModal",
    "StackSettingsModal",
    "advanced_item_type_embed",
    "mechanics_embed",
]
