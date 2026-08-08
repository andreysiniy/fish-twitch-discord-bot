"""Item wizard orchestrator (spec §6/§60).

Drives the create flow through the step views: template → basic info → rarity →
mechanics → effects → review. Every step loads the Redis session, mutates the
draft, saves it back and renders the next screen. Confirm is only reachable
from REVIEW, so a half-finished draft never reaches the backend (spec §44).
"""

from typing import Any

import discord

from app.domain.item_ui_registry import ITEM_TEMPLATES
from app.interactions.effects_editor import EffectsEditorView
from app.interactions.item_wizard import ItemPreviewView, build_item_payload
from app.interactions.items.basic_info import BasicInfoModal
from app.interactions.items.mechanics import MechanicsView, mechanics_embed
from app.interactions.items.rarity import RarityView, rarity_embed
from app.interactions.items.session import ItemWizardSession, WizardStep
from app.interactions.items.template_select import TemplateSelectView, template_embed

CONFIRM_TIMEOUT_SECONDS = 180


def template_choices() -> list[discord.app_commands.Choice[str]]:
    return [
        discord.app_commands.Choice(name=item["label"], value=item["value"])
        for item in ITEM_TEMPLATES
    ]


async def start_item_create(
    interaction: discord.Interaction,
    sessions,
    api,
    *,
    template: str | None = None,
) -> None:
    """Entry point for ``/fish item create`` (spec §5/§7)."""
    session = await ItemWizardSession.create(
        sessions,
        flow_type="item_create",
        discord_user_id=interaction.user.id,
        discord_guild_id=interaction.guild_id,
        channel_id=interaction.channel_id,
        template=template,
    )
    if template:
        session.apply_template_defaults()
        await session.transition(WizardStep.BASIC_INFO)
        await _render_basic_info(interaction, session, api)
    else:
        await _render_template(interaction, session, api)


async def _render_template(
    interaction: discord.Interaction, session: ItemWizardSession, api
) -> None:
    async def on_continue(done: discord.Interaction, template: str) -> None:
        try:
            session.template = template
            session.apply_template_defaults()
            await session.transition(WizardStep.BASIC_INFO)
        except (KeyError, ValueError):
            await done.response.send_message(
                "Unknown template. Run /fish item create again.", ephemeral=True
            )
            await session.delete()
            return
        await _render_basic_info(done, session, api)

    async def on_cancel(done: discord.Interaction) -> None:
        await session.delete()
        await done.response.edit_message(content="Item creation cancelled.", embed=None, view=None)

    view = TemplateSelectView(interaction.user.id, on_continue, on_cancel)
    if interaction.response.is_done():
        await interaction.edit_original_response(
            content=None,
            embed=template_embed(),
            view=view,
        )
    else:
        await interaction.response.send_message(
            embed=template_embed(),
            view=view,
            ephemeral=True,
        )


async def _render_basic_info(
    interaction: discord.Interaction, session: ItemWizardSession, api
) -> None:
    async def on_submit(done: discord.Interaction, values: dict[str, Any]) -> None:
        session.draft.update(values)
        await session.transition(WizardStep.RARITY)
        await _render_rarity(done, session, api)

    modal = BasicInfoModal(on_submit, current=session.draft)
    if interaction.response.is_done():
        await interaction.edit_original_response(
            content="Enter the item's basic information.", embed=None, view=None
        )
    await interaction.response.send_modal(modal)


async def _render_rarity(interaction: discord.Interaction, session: ItemWizardSession, api) -> None:
    async def on_continue(done: discord.Interaction, rarity: str) -> None:
        session.draft["rarity"] = rarity
        await session.transition(WizardStep.MECHANICS)
        await _render_mechanics(done, session, api)

    async def on_back(done: discord.Interaction) -> None:
        await session.transition(WizardStep.BASIC_INFO)
        await _render_basic_info(done, session, api)

    async def on_cancel(done: discord.Interaction) -> None:
        await session.delete()
        await done.response.edit_message(content="Item creation cancelled.", embed=None, view=None)

    view = RarityView(
        interaction.user.id,
        on_continue,
        on_back,
        on_cancel,
        current=session.draft.get("rarity", "common"),
    )
    await interaction.response.edit_message(
        content=None, embed=rarity_embed(view._selected), view=view
    )


async def _render_mechanics(
    interaction: discord.Interaction, session: ItemWizardSession, api
) -> None:
    async def on_persist(done: discord.Interaction) -> None:
        await session.save()
        view = _build_mechanics_view(session, api)
        await done.response.edit_message(
            content=None, embed=mechanics_embed(session.draft), view=view
        )

    async def on_continue(done: discord.Interaction) -> None:
        await session.transition(WizardStep.EFFECTS)
        await _render_effects(done, session, api)

    async def on_back(done: discord.Interaction) -> None:
        await session.transition(WizardStep.RARITY)
        await _render_rarity(done, session, api)

    async def on_cancel(done: discord.Interaction) -> None:
        await session.delete()
        await done.response.edit_message(content="Item creation cancelled.", embed=None, view=None)

    view = _build_mechanics_view(session, api, on_persist, on_continue, on_back, on_cancel)
    await interaction.response.edit_message(
        content=None, embed=mechanics_embed(session.draft), view=view
    )


def _build_mechanics_view(
    session: ItemWizardSession,
    api,
    on_persist=None,
    on_continue=None,
    on_back=None,
    on_cancel=None,
) -> MechanicsView:
    template = session.template or "material"

    async def default_persist(done: discord.Interaction) -> None:
        await session.save()
        await _render_mechanics(done, session, api)

    async def default_continue(done: discord.Interaction) -> None:
        await session.transition(WizardStep.EFFECTS)
        await _render_effects(done, session, api)

    async def default_back(done: discord.Interaction) -> None:
        await session.transition(WizardStep.RARITY)
        await _render_rarity(done, session, api)

    async def default_cancel(done: discord.Interaction) -> None:
        await session.delete()
        await done.response.edit_message(content="Item creation cancelled.", embed=None, view=None)

    return MechanicsView(
        initiator_id=int(session.discord_user_id),
        template=template,
        draft=session.draft,
        on_persist=on_persist or default_persist,
        on_continue=on_continue or default_continue,
        on_back=on_back or default_back,
        on_cancel=on_cancel or default_cancel,
    )


async def _render_effects(
    interaction: discord.Interaction, session: ItemWizardSession, api
) -> None:
    async def on_done(done: discord.Interaction, final_effects) -> None:
        if final_effects is None:
            await session.delete()
            await done.response.edit_message(
                content="Item creation cancelled.", embed=None, view=None
            )
            return
        session.draft["effects"] = final_effects
        await session.transition(WizardStep.REVIEW)
        await _render_review(done, session, api)

    view = EffectsEditorView(
        int(session.discord_user_id),
        list(session.draft.get("effects") or []),
        on_done,
    )
    await interaction.response.edit_message(
        content=view.message_text, embed=view._embed(), view=view
    )


async def _render_review(interaction: discord.Interaction, session: ItemWizardSession, api) -> None:
    async def _delete() -> None:
        try:
            await session.delete()
        except Exception:
            pass

    async def confirm(done: discord.Interaction) -> None:
        # Imported lazily: app.commands.shared pulls in the command tree, which
        # imports this module — a module-scope import would be circular.
        from app.commands.shared import _mutation_response

        payload = build_item_payload(session.draft)
        key = f"discord:item-create:{session.flow_id}"
        await _mutation_response(
            done, lambda: api.upsert_item(done, payload, idempotency_key=key), "Item created."
        )
        await _delete()

    async def on_edit_effects(editor_interaction: discord.Interaction) -> None:
        state = await session.store.get(session.discord_user_id, session.flow_id)
        effects = list((state or {}).get("draft", {}).get("effects") or [])

        async def effects_done(done_interaction: discord.Interaction, final_effects) -> None:
            if final_effects is None:
                await done_interaction.followup.send(
                    "Effect editing cancelled; the item draft is unchanged.",
                    ephemeral=True,
                )
                return
            session.draft["effects"] = final_effects
            await session.save()
            await _render_review(done_interaction, session, api)

        editor = EffectsEditorView(int(session.discord_user_id), effects, effects_done)
        await editor_interaction.response.edit_message(
            content=editor.message_text,
            embed=editor._embed(),
            view=editor,
        )

    async def on_cancel(cancel_interaction: discord.Interaction) -> None:
        await _delete()

    view = ItemPreviewView(
        int(session.discord_user_id),
        session.draft,
        confirm,
        on_edit_effects=on_edit_effects,
        on_cancel=on_cancel,
    )
    embed = view.embed()
    embed.title = f"Review item: {session.draft.get('title', session.draft.get('item_id'))}"
    await interaction.edit_original_response(content=None, embed=embed, view=view)
