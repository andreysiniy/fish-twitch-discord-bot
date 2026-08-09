"""Discord /fish items commands (module-per-domain)."""

import io
import json

import discord
from discord import app_commands

from app.api.errors import EngineError
from app.api.idempotency import interaction_key
from app.domain.item_review import compatibility_issues
from app.domain.item_ui_registry import TEMPLATES_BY_VALUE, validate_item_id
from app.interactions.confirms import ConfirmView
from app.interactions.item_wizard import build_item_payload
from app.interactions.items.review import review_embed
from app.interactions.items.wizard import (
    start_effect_edit,
    start_item_create,
    start_item_edit,
    template_choices,
)
from app.presentation.embeds import (
    item_detail_embed,
    item_list_entry,
)
from app.presentation.pagination import PagedEmbedView

from app.commands.shared import (  # noqa: F401  (shared helpers)
    BREAK_POLICY_CHOICES,
    EQUIPMENT_SLOT_CHOICES,
    ITEM_TYPE_CHOICES,
    MODIFIER_OPERATION_CHOICES,
    MODIFIER_SCOPE_CHOICES,
    RARITY_CHOICES,
    REWARD_CHOICES,
    SECTION_CHOICES,
    STAT_KEY_CHOICES,
    _confirmation,
    _deferred,
    _error_text,
    _json_confirmation,
    _json_embed,
    _mutation_response,
    _parse_effects,
    _player_modifier_preview_embed,
    _require_owner,
    _send_error,
    _send_json_embed,
    _session,
    _simple_mutation,
)

# Fields an import-json payload may carry. Every other key (including backend
# bookkeeping such as ``id``/``is_active``/``created_at``) is ignored so a raw
# export round-trips through the same payload builder the wizard uses.
_IMPORT_PAYLOAD_FIELDS = (
    "item_id",
    "title",
    "description",
    "item_type",
    "equipment_slot",
    "rarity",
    "stack_size",
    "max_durability",
    "max_charges",
    "break_policy",
    "schema_version",
    "effects",
    "image_url",
    "value",
)


def _draft_from_import_payload(raw: dict) -> dict:
    draft = {key: raw[key] for key in _IMPORT_PAYLOAD_FIELDS if key in raw}
    expected_version = raw.get("expected_version")
    if expected_version is None and raw.get("version") is not None:
        expected_version = raw["version"]
    if expected_version is not None:
        draft["expected_version"] = expected_version
    return draft


def _validate_import_draft(draft: dict) -> None:
    item_id = str(draft.get("item_id") or "").strip().lower()
    if not item_id:
        raise ValueError("The JSON must include a non-empty item_id.")
    if not validate_item_id(item_id):
        raise ValueError("item_id must be 1-120 lowercase letters, digits, '_' or '-'.")
    if not str(draft.get("title") or "").strip():
        raise ValueError("The JSON must include a non-empty title.")
    effects = draft.get("effects")
    if effects is not None and (
        not isinstance(effects, list) or not all(isinstance(effect, dict) for effect in effects)
    ):
        raise ValueError("effects must be a JSON array of objects.")


def register_items_group(tree, api, sessions, fish) -> None:
    item = app_commands.Group(name="item", description="Manage typed item definitions", parent=fish)

    @item.command(name="list", description="List typed item definitions")
    async def item_list(interaction: discord.Interaction, include_archived: bool = False) -> None:
        async def operation() -> None:
            result = await api.items(interaction, include_archived)
            view = PagedEmbedView(
                interaction.user.id,
                "Item definitions",
                result["items"],
                item_list_entry,
                page_size=8,
            )
            await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True)

        await _deferred(interaction, operation)

    @item.command(name="show", description="Show every field of one item definition")
    async def item_show(interaction: discord.Interaction, item_id: str) -> None:
        async def operation() -> None:
            result = await api.item(interaction, item_id)
            await interaction.followup.send(embed=item_detail_embed(result), ephemeral=True)

        await _deferred(interaction, operation)

    @item.command(name="create", description="Create a typed item with the step-by-step wizard")
    @app_commands.choices(template=template_choices())
    @app_commands.describe(template="Optional template to prefill the wizard")
    async def item_create(
        interaction: discord.Interaction,
        template: str | None = None,
    ) -> None:
        if template and template not in TEMPLATES_BY_VALUE:
            await interaction.response.send_message(
                "Unknown template. Run /fish item create without arguments.", ephemeral=True
            )
            return
        try:
            await start_item_create(interaction, sessions, api, template=template)
        except (EngineError, ValueError) as error:
            content = _error_text(error)
            if interaction.response.is_done():
                await interaction.followup.send(content, ephemeral=True)
            else:
                await interaction.response.send_message(content, ephemeral=True)

    @item.command(name="edit", description="Edit an item definition with the step-by-step wizard")
    @app_commands.describe(item_id="Existing stable item ID")
    async def item_edit(interaction: discord.Interaction, item_id: str) -> None:
        try:
            await start_item_edit(interaction, sessions, api, item_id=item_id)
        except (EngineError, ValueError) as error:
            content = _error_text(error)
            if interaction.response.is_done():
                await interaction.followup.send(content, ephemeral=True)
            else:
                await interaction.response.send_message(content, ephemeral=True)

    @item.command(name="effect-edit", description="Edit the typed effects of an item without JSON")
    @app_commands.describe(item_id="Existing stable item ID")
    async def item_effect_edit(interaction: discord.Interaction, item_id: str) -> None:
        try:
            await start_effect_edit(interaction, sessions, api, item_id=item_id)
        except (EngineError, ValueError) as error:
            content = _error_text(error)
            if interaction.response.is_done():
                await interaction.followup.send(content, ephemeral=True)
            else:
                await interaction.response.send_message(content, ephemeral=True)

    @item.command(
        name="export-json",
        description="Export an item definition as raw JSON (Twitch channel owner only)",
    )
    @app_commands.describe(item_id="Existing stable item ID")
    async def item_export_json(interaction: discord.Interaction, item_id: str) -> None:
        try:
            await _require_owner(api, interaction)
            result = await api.item(interaction, item_id)
        except (EngineError, ValueError) as error:
            await _send_error(interaction, error)
            return
        raw = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        embed = _json_embed("Exported item", result)
        if interaction.response.is_done():
            await interaction.followup.send(
                embed=embed,
                file=discord.File(io.StringIO(raw), filename=f"{item_id}.json"),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                embed=embed,
                file=discord.File(io.StringIO(raw), filename=f"{item_id}.json"),
                ephemeral=True,
            )

    @item.command(
        name="import-json",
        description="Import an item definition from raw JSON (Twitch channel owner only)",
    )
    @app_commands.describe(payload="Raw item definition JSON")
    async def item_import_json(interaction: discord.Interaction, payload: str) -> None:
        try:
            await _require_owner(api, interaction)
            raw = json.loads(payload)
        except json.JSONDecodeError as error:
            await interaction.response.send_message(f"Invalid JSON: {error.msg}", ephemeral=True)
            return
        except (EngineError, ValueError) as error:
            await _send_error(interaction, error)
            return
        if not isinstance(raw, dict):
            await interaction.response.send_message(
                "The JSON payload must be an object.", ephemeral=True
            )
            return
        draft = _draft_from_import_payload(raw)
        try:
            _validate_import_draft(draft)
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        errors, _ = compatibility_issues(draft)
        embed = review_embed(
            draft,
            schema_version=draft.get("schema_version", 1),
            version=draft.get("expected_version"),
        )
        if errors:
            await interaction.response.send_message(
                "The JSON has blocking compatibility errors. Fix the file and run the command again.",
                embed=embed,
                ephemeral=True,
            )
            return

        async def confirm(confirmed: discord.Interaction) -> None:
            # Spec §56: the confirm callback re-checks the actor identity before
            # the backend mutation, even though the backend re-authorizes too.
            await _require_owner(api, confirmed)
            await _mutation_response(
                confirmed,
                lambda: api.upsert_item(
                    confirmed,
                    build_item_payload(draft),
                    idempotency_key=interaction_key(interaction.id, "item.import"),
                ),
                "Item imported.",
            )

        await interaction.response.send_message(
            "Review the imported item, then confirm to save it.",
            embed=embed,
            view=ConfirmView(interaction.user.id, confirm),
            ephemeral=True,
        )

    @item.command(name="archive", description="Archive an item without deleting history")
    async def item_archive(interaction: discord.Interaction, item_id: str) -> None:
        try:
            current = await api.item(interaction, item_id)
        except EngineError as error:
            await _send_error(interaction, error)
            return
        await _confirmation(
            interaction,
            f"Archive item `{item_id}`? Existing inventory rows are preserved.",
            lambda confirmed: api.archive_item(confirmed, item_id, current["version"]),
            "Item archived.",
            danger=True,
        )

    return {
        "item_list": item_list,
        "item_show": item_show,
        "item_create": item_create,
        "item_edit": item_edit,
        "item_effect_edit": item_effect_edit,
        "item_export_json": item_export_json,
        "item_import_json": item_import_json,
        "item_archive": item_archive,
    }
