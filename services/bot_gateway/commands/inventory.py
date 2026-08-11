import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from api_client import EngineApiError
from heplers.context_tool import get_channel_id
from twitchio.ext import commands

logger = logging.getLogger(__name__)


class InventoryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="fishbag")
    async def fishbag(self, ctx: commands.Context, *args: str) -> None:
        target_name, slot_id, error = self._parse_fishbag_args(args)
        if error:
            await ctx.send(error)
            return

        channel_id = await get_channel_id(ctx)
        target = ctx.author
        if target_name is not None:
            target = await self._resolve_user(target_name)
            if target is None:
                await ctx.send(f"Viewer {target_name} was not found.")
                return

        try:
            response = await self.bot.api_client.get_inventory(
                channel_id=channel_id,
                user_id=str(target.id),
            )
            if slot_id is None:
                await self._send_inventory(ctx, response, owner_name=target.name)
            else:
                await self._send_item_details(
                    ctx,
                    response,
                    slot_id=slot_id,
                    owner_name=target.name,
                )
        except EngineApiError as error:
            await ctx.send(f"Inventory error: {error}")
        except Exception:
            logger.exception("Fish inventory command failed")
            await ctx.send("Could not retrieve inventory.")

    async def _resolve_user(self, username: str):
        fetch_users = getattr(self.bot, "fetch_users", None)
        if fetch_users is None:
            return None
        try:
            users = await fetch_users(names=[username])
        except Exception:
            logger.exception("Failed to resolve Twitch user", extra={"username": username})
            return None
        return users[0] if users else None

    @staticmethod
    def _parse_fishbag_args(args: tuple[str, ...]) -> tuple[str | None, int | None, str | None]:
        """Parse ``!fishbag`` as an optional viewer and an optional slot.

        A single number selects a slot of the command author. A single
        non-number selects a viewer inventory, and a viewer followed by a
        number selects that viewer's slot.
        """
        if len(args) > 2:
            return None, None, "Usage: !fishbag [viewer] [slot]"

        values = tuple(str(value).strip() for value in args)
        if not values:
            return None, None, None
        if any(not value for value in values):
            return None, None, "Usage: !fishbag [viewer] [slot]"

        if len(values) == 1:
            try:
                slot_id = int(values[0])
            except ValueError:
                return values[0].lstrip("@"), None, None
            if slot_id <= 0:
                return None, None, "Slot must be a positive number."
            return None, slot_id, None

        try:
            slot_id = int(values[1])
        except ValueError:
            return None, None, "Usage: !fishbag [viewer] [slot]"
        if slot_id <= 0:
            return None, None, "Slot must be a positive number."
        username = values[0].lstrip("@")
        if not username:
            return None, None, "Usage: !fishbag [viewer] [slot]"
        return username, slot_id, None

    @commands.command(name="fishequip")
    async def fishequip(self, ctx: commands.Context, slot_id: str | None = None) -> None:
        channel_id = await get_channel_id(ctx)
        try:
            parsed_slot = int(slot_id) if slot_id else None
        except ValueError:
            # Non-numeric input: the engine answers with the usage message.
            parsed_slot = None
        payload = {
            "user_id": str(ctx.author.id),
            "channel_id": channel_id,
            "slot_id": parsed_slot,
        }
        try:
            response = await self.bot.api_client.equip_item(payload)
            await ctx.send(response.get("message", "Item equipped."))
        except EngineApiError as error:
            await ctx.send(f"Equip error: {error}")
        except Exception:
            logger.exception("Fish equip command failed")
            await ctx.send("Could not equip item.")

    async def _send_inventory(
        self,
        ctx,
        response: dict,
        *,
        owner_name: str | None = None,
    ) -> None:
        items = response.get("items", [])
        if not items:
            message = f"{owner_name}'s inventory is empty." if owner_name else "Inventory is empty."
            await ctx.send(message)
            return

        equipped_by_slot = response.get("equipped_slots") or {}
        max_slots = int(response.get("max_slots") or 0)
        lines = []
        for item in items[:8]:
            slot_id = item.get("slot_id", "?")
            name = item.get("title", "Unknown")
            qty = item.get("quantity", 1)
            # equipped_slots maps an equipment slot (rod/bait/...) to the
            # inventory slot number that is currently worn.
            equipped = (
                equipped_by_slot.get(item.get("equipment_slot")) == item.get("slot_id")
            )
            marker = " [EQUIPPED]" if equipped else ""
            durability = ""
            max_durability = item.get("max_durability")
            if max_durability is not None:
                current = item.get("current_durability")
                durability = f" (durability {current}/{max_durability})"
            max_charges = item.get("max_charges")
            charges = (
                f" (charges {item.get('current_charges')}/{max_charges})"
                if max_charges is not None
                else ""
            )
            item_type = item.get("item_type")
            rarity = item.get("rarity")
            kind = f" [{rarity} {item_type}]" if rarity and item_type else ""
            lines.append(f"[{slot_id}] {name} x{qty}{kind}{marker}{durability}{charges}")

        owner_prefix = f"{owner_name}'s " if owner_name else ""
        inventory_word = "inventory" if owner_name else "Inventory"
        header = (
            f"{owner_prefix}{inventory_word} {len(items)}/{max_slots} slots: "
            if max_slots
            else f"{owner_prefix}{inventory_word}: "
        )
        await ctx.send(header + ", ".join(lines))

    async def _send_item_details(
        self,
        ctx,
        response: dict,
        *,
        slot_id: int,
        owner_name: str | None = None,
    ) -> None:
        item = next(
            (
                candidate
                for candidate in response.get("items", [])
                if candidate.get("slot_id") == slot_id
            ),
            None,
        )
        if item is None:
            owner_prefix = f"{owner_name} has" if owner_name else "You have"
            await ctx.send(f"{owner_prefix} no item in slot {slot_id}.")
            return

        title = item.get("title", "Unknown item")
        owner_prefix = f"{owner_name}'s " if owner_name else "Your "
        details = [f"{owner_prefix}item [{slot_id}] {title} x{item.get('quantity', 1)}"]
        item_type = item.get("item_type")
        rarity = item.get("rarity")
        if rarity or item_type:
            details.append(f"Type: {item_type or 'unknown'}; rarity: {rarity or 'unknown'}")

        max_durability = item.get("max_durability")
        if max_durability is not None:
            details.append(
                f"Durability: {item.get('current_durability')}/{max_durability}"
            )
        max_charges = item.get("max_charges")
        if max_charges is not None:
            details.append(f"Charges: {item.get('current_charges')}/{max_charges}")

        effect_lines = self._format_effects(item.get("effects") or [])
        if effect_lines:
            details.append("Effects: " + "; ".join(effect_lines))
        await ctx.send(". ".join(details) + ".")

    @classmethod
    def _format_effects(cls, effects: list[Any]) -> list[str]:
        formatted: list[str] = []
        for effect in effects:
            if not isinstance(effect, dict):
                continue
            effect_type = str(effect.get("type") or "").strip().lower()
            if effect_type in {"stat_add", "stat_multiply"}:
                value = cls._format_stat_effect(effect, effect_type)
            else:
                value = cls._format_action_effect(effect, effect_type)
            if value:
                formatted.append(value)
        return formatted

    @classmethod
    def _format_stat_effect(cls, effect: dict[str, Any], effect_type: str) -> str:
        stat = str(effect.get("stat") or "").strip()
        if not stat:
            return ""
        label = cls._stat_label(stat)
        try:
            raw_value = Decimal(str(effect.get("value")))
        except (InvalidOperation, TypeError, ValueError):
            return f"{label}: unavailable"

        flat_stats = {"points_flat_bonus", "protected_mass_flat", "inventory_slots_add"}
        if stat in flat_stats:
            value = raw_value
            suffix = ""
        elif effect_type == "stat_multiply":
            value = (raw_value - Decimal(1)) * Decimal(100)
            suffix = "%"
        else:
            value = raw_value * Decimal(100)
            suffix = "%"
        return f"{label} {cls._signed_number(value)}{suffix}"

    @classmethod
    def _format_action_effect(cls, effect: dict[str, Any], effect_type: str) -> str:
        if not effect_type:
            return ""
        if effect_type == "reroll_reward":
            targets = ", ".join(str(value) for value in effect.get("target_action_types") or [])
            count = effect.get("max_rerolls", 1)
            return f"Reroll {targets or 'rewards'} up to {count} time(s)"
        if effect_type == "block_action":
            targets = ", ".join(str(value) for value in effect.get("target_action_types") or [])
            chance = cls._percentage(effect.get("chance"))
            return f"Block {targets or 'actions'} ({chance} chance)"
        if effect_type in {"robbery_counter", "absorb_robbery"}:
            chance = cls._percentage(effect.get("chance"))
            return f"{cls._title_case(effect_type)} ({chance} chance)"
        if effect_type == "mass_floor":
            mass = effect.get("protected_mass", 0)
            scopes = ", ".join(str(value) for value in effect.get("scopes") or [])
            return f"Protect {mass} mass ({scopes or 'all applicable scopes'})"
        if effect_type == "grant_item":
            return f"Grant {effect.get('quantity', 1)}x {effect.get('item_id', 'item')}"
        if effect_type == "grant_mass":
            return f"Grant {effect.get('mass', 0)} mass"
        if effect_type in {"apply_timeout", "timeout"}:
            duration = effect.get("duration_seconds", effect.get("duration", 0))
            return f"Timeout for {duration} seconds"
        if effect_type == "loot_table_roll":
            table = effect.get("loot_table_id", "loot table")
            return f"Roll {table} ({effect.get('rolls', 1)} time(s))"
        if effect_type in {"consume_durability", "consume_charge"}:
            noun = "durability" if effect_type == "consume_durability" else "charge"
            return f"Consume {effect.get('amount', 1)} {noun}"
        return cls._title_case(effect_type)

    @staticmethod
    def _stat_label(stat: str) -> str:
        labels = {
            "fish_luck_change_ratio": "Fish Luck",
            "positive_fish_reward_change_ratio": "Positive Fish Reward",
            "negative_fish_reward_change_ratio": "Negative Fish Reward",
            "xp_gain_change_ratio": "XP",
            "cooldown_change_ratio": "Cooldown",
            "points_flat_bonus": "Points",
            "item_drop_chance_add": "Item Drop Chance",
            "item_rarity_luck_pct": "Item Rarity",
            "empty_catch_reroll_chance_pct": "Empty Catch Reroll",
            "robbery_protection_pct": "Robbery Protection",
            "robbery_evasion_pct": "Robbery Evasion",
            "protected_mass_flat": "Protected Mass",
            "robbery_counter_chance_pct": "Robbery Counter Chance",
            "robbery_attack_chance_add": "Robbery Attack Chance",
            "robbery_amount_bonus_pct": "Robbery Amount",
            "inventory_slots_add": "Inventory Slots",
            "sell_rate_bonus_pct": "Sell Rate",
            "buy_discount_pct": "Buy Discount",
        }
        return labels.get(stat, InventoryCog._title_case(stat))

    @staticmethod
    def _signed_number(value: Decimal) -> str:
        rendered = format(value, "f").rstrip("0").rstrip(".")
        if rendered in {"", "-0"}:
            rendered = "0"
        if not rendered.startswith("-"):
            rendered = "+" + rendered
        return rendered

    @classmethod
    def _percentage(cls, value: Any) -> str:
        try:
            rendered = Decimal(str(value)) * Decimal(100)
        except (InvalidOperation, TypeError, ValueError):
            return "unknown"
        return f"{format(rendered, 'f').rstrip('0').rstrip('.')}%"

    @staticmethod
    def _title_case(value: str) -> str:
        return value.replace("_", " ").strip().capitalize()
