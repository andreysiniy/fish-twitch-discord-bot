"""Item wizard orchestrator (spec §6/§60).

Drives the create flow through the step views: template → basic info → rarity →
mechanics → effects → review. Every step loads the Redis session, mutates the
draft, saves it back and renders the next screen. Confirm is only reachable
from REVIEW, so a half-finished draft never reaches the backend (spec §44).

``/fish item edit`` (spec §54) reuses the same views: the draft is seeded from
the backend definition with ``expected_version`` set so the backend optimistic
lock rejects stale saves, and the final button reads "Save Changes". A
``ITEM_VERSION_CONFLICT`` (spec §55) keeps the flow open and offers to reload
the latest version instead of silently overwriting a newer definition.
"""

from typing import Any

import discord

from app.api.errors import EngineError
from app.domain.item_ui_registry import (
    ITEM_TEMPLATES,
    TEMPLATES_BY_VALUE,
    template_for_item_type,
)
from app.interactions.item_wizard import build_item_payload
from app.interactions.items.basic_info import BasicInfoModal
from app.interactions.items.effects import ItemEffectsView
from app.interactions.items.mechanics import MechanicsView, mechanics_embed
from app.interactions.items.rarity import RarityView, rarity_embed
from app.interactions.items.review import ItemReviewView, VersionConflictView
from app.interactions.items.session import ItemWizardSession, WizardStep
from app.interactions.items.template_select import TemplateSelectView, template_embed

CONFIRM_TIMEOUT_SECONDS = 180


def template_choices() -> list[discord.app_commands.Choice[str]]:
    return [
        discord.app_commands.Choice(name=item["label"], value=item["value"])
        for item in ITEM_TEMPLATES
    ]


def _restart_text(session: ItemWizardSession) -> str:
    return (
        "Run /fish item edit again."
        if session.flow_type == "item_edit"
        else "Run /fish item create again."
    )


def _cancel_text(session: ItemWizardSession) -> str:
    return (
        "Item edit cancelled." if session.flow_type == "item_edit" else "Item creation cancelled."
    )


async def _render_step(
    interaction: discord.Interaction,
    *,
    content: str | None = None,
    embed: discord.Embed | None = None,
    view: discord.ui.View,
) -> None:
    """Render the next wizard step onto the interaction's message.

    Component clicks and modals launched from a message component update that
    message in place. A modal opened straight from a slash command has no
    parent message (``interaction.message`` is None), so Discord rejects
    ``edit_message`` with 404; in that case reply with a fresh ephemeral
    message carrying the next step instead.
    """
    if interaction.message is not None:
        await interaction.response.edit_message(content=content, embed=embed, view=view)
    else:
        await interaction.response.send_message(
            content=content, embed=embed, view=view, ephemeral=True
        )


def _seed_draft_from_item(item_id: str, current: dict[str, Any]) -> dict[str, Any]:
    """Translate a backend item definition into a wizard draft (spec §54).

    The edit draft carries the backend's current version so the confirm submit
    can use optimistic locking: a stale draft is rejected with
    ``ITEM_VERSION_CONFLICT`` and the flow stays open (spec §55).
    """
    return {
        "item_id": item_id,
        "title": current.get("title", ""),
        "item_type": current.get("item_type", "material"),
        "rarity": current.get("rarity", "common"),
        "equipment_slot": current.get("equipment_slot"),
        "stack_size": current.get("stack_size", 1),
        "max_durability": current.get("max_durability"),
        "max_charges": current.get("max_charges"),
        "break_policy": current.get("break_policy", "indestructible"),
        "effects": list(current.get("effects") or []),
        "description": current.get("description"),
        "schema_version": current.get("schema_version", 1),
        "image_url": current.get("image_url"),
        "value": current.get("value"),
        "expected_version": current.get("version"),
    }


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


async def start_item_edit(
    interaction: discord.Interaction,
    sessions,
    api,
    *,
    item_id: str,
) -> None:
    """Entry point for ``/fish item edit`` (spec §54).

    Fetches the current definition, seeds the draft from it and jumps straight
    to Basic Info so the admin edits a complete item instead of rebuilding it.
    """
    current = await api.item(interaction, item_id)
    template = template_for_item_type(
        current.get("item_type", "material"), current.get("equipment_slot")
    )
    session = await ItemWizardSession.create(
        sessions,
        flow_type="item_edit",
        discord_user_id=interaction.user.id,
        discord_guild_id=interaction.guild_id,
        channel_id=interaction.channel_id,
        template=template,
        draft=_seed_draft_from_item(item_id, current),
        expected_version=current.get("version"),
        step=WizardStep.BASIC_INFO,
    )
    await _render_basic_info(interaction, session, api)


async def start_effect_edit(
    interaction: discord.Interaction,
    sessions,
    api,
    *,
    item_id: str,
) -> None:
    """Entry point for ``/fish item effect-edit`` (spec §54).

    Loads the current definition into an edit session at the Effects step and
    opens the typed effects editor directly. Completing the editor routes to the
    shared review screen so the admin can still adjust anything before saving.
    """
    current = await api.item(interaction, item_id)
    template = template_for_item_type(
        current.get("item_type", "material"), current.get("equipment_slot")
    )
    session = await ItemWizardSession.create(
        sessions,
        flow_type="item_edit",
        discord_user_id=interaction.user.id,
        discord_guild_id=interaction.guild_id,
        channel_id=interaction.channel_id,
        template=template,
        draft=_seed_draft_from_item(item_id, current),
        expected_version=current.get("version"),
        step=WizardStep.EFFECTS,
    )

    async def on_done(done: discord.Interaction, final_effects) -> None:
        if final_effects is None:
            await session.delete()
            await done.response.edit_message(content=_cancel_text(session), embed=None, view=None)
            return
        session.draft["effects"] = final_effects
        await session.transition(WizardStep.REVIEW)
        await _render_review(done, session, api)

    view = ItemEffectsView(
        int(session.discord_user_id),
        list(session.draft.get("effects") or []),
        on_done,
        api=api,
        restart_text=_restart_text(session),
    )
    await interaction.response.send_message(
        view.message_text, embed=view._embed(), view=view, ephemeral=True
    )


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
                f"Unknown template. {_restart_text(session)}", ephemeral=True
            )
            await session.delete()
            return
        await _render_basic_info(done, session, api)

    async def on_cancel(done: discord.Interaction) -> None:
        await session.delete()
        await done.response.edit_message(content=_cancel_text(session), embed=None, view=None)

    view = TemplateSelectView(
        interaction.user.id,
        on_continue,
        on_cancel,
        restart_text=_restart_text(session),
    )
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
        await done.response.edit_message(content=_cancel_text(session), embed=None, view=None)

    view = RarityView(
        interaction.user.id,
        on_continue,
        on_back,
        on_cancel,
        current=session.draft.get("rarity", "common"),
        restart_text=_restart_text(session),
    )
    await _render_step(interaction, embed=rarity_embed(view._selected), view=view)


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
        await done.response.edit_message(content=_cancel_text(session), embed=None, view=None)

    view = _build_mechanics_view(session, api, on_persist, on_continue, on_back, on_cancel)
    await _render_step(interaction, embed=mechanics_embed(session.draft), view=view)


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
        await done.response.edit_message(content=_cancel_text(session), embed=None, view=None)

    return MechanicsView(
        initiator_id=int(session.discord_user_id),
        template=template,
        draft=session.draft,
        on_persist=on_persist or default_persist,
        on_continue=on_continue or default_continue,
        on_back=on_back or default_back,
        on_cancel=on_cancel or default_cancel,
        restart_text=_restart_text(session),
    )


async def _render_effects(
    interaction: discord.Interaction, session: ItemWizardSession, api
) -> None:
    async def on_done(done: discord.Interaction, final_effects) -> None:
        if final_effects is None:
            await session.delete()
            await done.response.edit_message(content=_cancel_text(session), embed=None, view=None)
            return
        session.draft["effects"] = final_effects
        await session.transition(WizardStep.REVIEW)
        await _render_review(done, session, api)

    async def on_back(done: discord.Interaction) -> None:
        await session.transition(WizardStep.MECHANICS)
        await _render_mechanics(done, session, api)

    view = ItemEffectsView(
        int(session.discord_user_id),
        list(session.draft.get("effects") or []),
        on_done,
        api=api,
        on_back=on_back,
        restart_text=_restart_text(session),
    )
    await _render_step(interaction, content=view.message_text, embed=view._embed(), view=view)


async def _render_review(interaction: discord.Interaction, session: ItemWizardSession, api) -> None:
    async def _delete() -> None:
        try:
            await session.delete()
        except Exception:
            pass

    async def confirm(done: discord.Interaction) -> None:
        # Spec §61: mark SUBMITTING in Redis before the backend call so a second
        # click or an HTTP retry can never create/update twice. Recoverable
        # errors move back to REVIEW and are re-rendered by the view.
        await session.transition(WizardStep.SUBMITTING)
        payload = build_item_payload(session.draft)
        is_edit = session.flow_type == "item_edit"
        key = (
            f"discord:item-edit:{session.flow_id}"
            if is_edit
            else f"discord:item-create:{session.flow_id}"
        )
        try:
            await api.upsert_item(done, payload, idempotency_key=key)
        except EngineError as error:
            try:
                await session.transition(WizardStep.REVIEW)
            except Exception:
                pass
            if error.code == "ITEM_VERSION_CONFLICT" and is_edit:
                await _render_conflict(done, session, api)
                return
            raise
        except Exception:
            try:
                await session.transition(WizardStep.REVIEW)
            except Exception:
                pass
            raise
        await _delete()
        message = "Item updated." if is_edit else "Item created."
        if done.response.is_done():
            await done.edit_original_response(content=message, embed=None, view=None)
        else:
            await done.response.send_message(message, ephemeral=True)

    async def on_edit_basic(editor_interaction: discord.Interaction) -> None:
        async def on_submit(done: discord.Interaction, values: dict) -> None:
            session.draft.update(values)
            await session.save()
            await _render_review(done, session, api)

        modal = BasicInfoModal(on_submit, current=session.draft)
        await editor_interaction.response.send_modal(modal)

    async def on_edit_mechanics(editor_interaction: discord.Interaction) -> None:
        view = _mechanics_review_view(session, api)
        await editor_interaction.response.edit_message(
            content=None, embed=mechanics_embed(session.draft), view=view
        )

    async def on_edit_effects(editor_interaction: discord.Interaction) -> None:
        state = await session.store.get(session.discord_user_id, session.flow_id)
        effects = list((state or {}).get("draft", {}).get("effects") or [])

        async def effects_done(done_interaction: discord.Interaction, final_effects) -> None:
            if final_effects is not None:
                session.draft["effects"] = final_effects
                await session.save()
            await _render_review(done_interaction, session, api)

        editor = ItemEffectsView(
            int(session.discord_user_id),
            effects,
            effects_done,
            api=api,
            on_back=lambda done: _render_review(done, session, api),
            restart_text=_restart_text(session),
        )
        await editor_interaction.response.edit_message(
            content=editor.message_text,
            embed=editor._embed(),
            view=editor,
        )

    async def on_cancel(cancel_interaction: discord.Interaction) -> None:
        await _delete()
        await cancel_interaction.response.edit_message(
            content=_cancel_text(session), embed=None, view=None
        )

    view = ItemReviewView(
        initiator_id=int(session.discord_user_id),
        draft=session.draft,
        confirm_label="Save Changes" if session.flow_type == "item_edit" else "Create Item",
        on_confirm=confirm,
        on_edit_basic=on_edit_basic,
        on_edit_mechanics=on_edit_mechanics,
        on_edit_effects=on_edit_effects,
        on_cancel=on_cancel,
        template_label=_template_label(session.template),
        schema_version=session.draft.get("schema_version", 1),
        version=session.expected_version,
        restart_text=_restart_text(session),
    )
    await _render_step(interaction, embed=view.embed(), view=view)


async def _render_conflict(
    interaction: discord.Interaction, session: ItemWizardSession, api
) -> None:
    """Show the optimistic-locking recovery card (spec §55)."""

    async def on_reload(done: discord.Interaction) -> None:
        item_id = session.draft.get("item_id")
        if not item_id:
            await session.delete()
            await done.response.edit_message(
                content="The item could not be reloaded. Run /fish item edit again.",
                embed=None,
                view=None,
            )
            return
        try:
            current = await api.item(done, item_id)
        except Exception:
            await done.response.edit_message(
                content="The item could not be reloaded. Try again.",
                embed=None,
                view=None,
            )
            return
        template = template_for_item_type(
            current.get("item_type", "material"), current.get("equipment_slot")
        )
        session.template = template or session.template
        session.draft = _seed_draft_from_item(item_id, current)
        session.expected_version = current.get("version")
        await session.save()
        await _render_review(done, session, api)

    async def on_cancel(done: discord.Interaction) -> None:
        await session.delete()
        await done.response.edit_message(content=_cancel_text(session), embed=None, view=None)

    view = VersionConflictView(
        initiator_id=int(session.discord_user_id),
        on_reload=on_reload,
        on_cancel=on_cancel,
    )
    if interaction.response.is_done():
        await interaction.edit_original_response(content=None, embed=view.embed(), view=view)
    else:
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)


def _template_label(template: str | None) -> str | None:
    """Human label for the session template (spec §8/§38)."""
    if not template:
        return None
    spec = TEMPLATES_BY_VALUE.get(template)
    return spec["label"] if spec else template.replace("_", " ").title()


def _mechanics_review_view(session: ItemWizardSession, api) -> MechanicsView:
    """Mechanics editor that returns to REVIEW instead of walking the wizard."""

    async def on_persist(done: discord.Interaction) -> None:
        await session.save()
        view = _mechanics_review_view(session, api)
        await done.response.edit_message(
            content=None, embed=mechanics_embed(session.draft), view=view
        )

    async def on_continue(done: discord.Interaction) -> None:
        await session.save()
        await _render_review(done, session, api)

    async def on_back(done: discord.Interaction) -> None:
        await _render_review(done, session, api)

    async def on_cancel(done: discord.Interaction) -> None:
        try:
            await session.delete()
        except Exception:
            pass
        await done.response.edit_message(content=_cancel_text(session), embed=None, view=None)

    return _build_mechanics_view(session, api, on_persist, on_continue, on_back, on_cancel)
