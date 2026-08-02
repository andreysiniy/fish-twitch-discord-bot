import random

from core.action_types import ActionType
from core.game_params import GParam, resolve_param
from core.messages import MsgKey, format_large_number_mass, format_percent_signed, resolve_message
from domain.item_schema import ModifierScope, StatKey
from domain.logic.formulas import calculate_xp_required
from domain.logic.mass import ZERO_MASS, quantize_mass
from domain.logic.stats_calculator import calculate_player_stats
from domain.schemas.fishing import (
    FishCooldownResponse,
    FishStatsResponse,
    FishTopResponse,
    RobberyResultDTO,
)
from infrastructure.models import UserProgress
from infrastructure.repositories import ChannelRepository, ConfigRepository, UserRepository
from infrastructure.repositories.cooldown_repo import CooldownRepository
from infrastructure.repositories.inventory_repo import InventoryRepository
from services.fishing.engine import FishingEngine
from services.fishing.presenter import FishingPresenter
from services.fishing.strategy_resolver import FishingStrategyResolver
from services.player_modifier_service import PlayerModifierService


class FishingService:
    def __init__(
        self,
        user_repo: UserRepository,
        config_repo: ConfigRepository,
        cooldown_repo: CooldownRepository,
        channel_repo: ChannelRepository,
    ):
        self.user_repo = user_repo
        self.config_repo = config_repo
        self.cooldown_repo = cooldown_repo
        self.channel_repo = channel_repo
        self.engine = FishingEngine()
        self.presenter = FishingPresenter()
        self.strategy_resolver = FishingStrategyResolver(channel_repo=channel_repo)
        self.modifier_service = PlayerModifierService(user_repo.db)

    def process_cast(
        self,
        twitch_id: str,
        username: str,
        channel_id: str,
        is_mod: bool = False,
        is_sub: bool = False,
        bypass_cooldown: bool = False,
    ):
        user = self.user_repo.get_progress(twitch_id, channel_id)
        if not user:
            user = self.user_repo.create(twitch_id, username, channel_id)

        channel_config = user.channel.config or {}
        custom_params = channel_config.get("custom_params", {})
        strategy_ctx = self.strategy_resolver.resolve(user.channel_id)
        fishing_modifiers = self.modifier_service.resolve(user, ModifierScope.FISHING)
        cooldown_duration = (
            0
            if bypass_cooldown
            else self._resolve_cooldown_duration(custom_params, is_mod, is_sub)
        )
        cooldown_multiplier = max(
            1.0 - float(fishing_modifiers.value(StatKey.COOLDOWN_REDUCTION_PCT)),
            0.0,
        )
        cooldown_duration = max(int(round(cooldown_duration * cooldown_multiplier)), 0)

        if cooldown_duration > 0:
            is_active, seconds_left = self.cooldown_repo.check_cooldown(channel_id, twitch_id)
            if is_active:
                return self.presenter.build_cooldown_response(
                    user=user, cooldown_duration=cooldown_duration, cooldown_left=seconds_left
                )

        location_id = user.current_location_id or "default"
        loot_pool, item_pool, rate = self.config_repo.get_dual_pool(channel_id, location_id)

        if strategy_ctx.override_loot_pool_location_id is not None:
            override_location_id = str(strategy_ctx.override_loot_pool_location_id).strip()
            if override_location_id:
                override_result = self.config_repo.get_dual_pool(channel_id, override_location_id)
                if override_result:
                    loot_pool, item_pool, rate = override_result

        behavioral_effects = list(fishing_modifiers.effects)
        result = self.engine.calculate_result(
            user=user,
            loot_pool=loot_pool,
            item_pool=item_pool,
            items_drop_rate=rate,
            custom_params=custom_params,
            calculation_strategy=strategy_ctx.calculation_strategy,
            modifier_values=fishing_modifiers.values,
            behavioral_effects=behavioral_effects,
            negative_mass_floor=fishing_modifiers.mass_floor("negative_rewards"),
            roulette_mass_floor=fishing_modifiers.mass_floor("roulette"),
        )

        if result.loot.get("type") == ActionType.ROBBERY:
            result.robbery_result = self._handle_robbery(result.loot, user)

        user.xp += result.xp_gained
        user.total_fish_stat += 1

        if result.is_level_up:
            user.level = result.new_level

        if result.mass_gained != 0:
            previous_mass = quantize_mass(user.current_mass)
            requested_mass_delta = quantize_mass(result.mass_gained)
            user.current_mass = max(
                quantize_mass(previous_mass + requested_mass_delta),
                ZERO_MASS,
            )
            applied_mass_delta = quantize_mass(user.current_mass - previous_mass)
            previous_total_mass = quantize_mass(user.total_mass_stat)
            user.total_mass_stat = quantize_mass(
                previous_total_mass + max(applied_mass_delta, ZERO_MASS)
            )
            result.mass_gained = applied_mass_delta

        if result.item_drop:
            if not result.item_drop.get("title"):
                result.item_drop["title"] = result.item_drop.get("item_id", "Unknown Item")
            if result.item_drop.get("quantity") is None:
                result.item_drop["quantity"] = 1

            location_item_id = result.item_drop.get("db_id")
            has_stock = not location_item_id or self.config_repo.consume_location_item_stock(
                location_item_id, amount=1
            )
            if has_stock:
                self.user_repo.update_inventory(user, result.item_drop)
            else:
                result.item_drop = None

        inventory_repo = InventoryRepository(self.user_repo.db)
        for effect in behavioral_effects:
            trigger_count = int(effect.pop("_trigger_count", 0))
            durability_cost = int(effect.get("durability_cost", 0)) * trigger_count
            if durability_cost:
                inventory_repo.consume_durability(
                    user.id,
                    str(effect.get("source_slot") or "charm_1"),
                    durability_cost,
                )

        result.broken_item_name = self.user_repo.apply_equipped_rod_durability_loss(
            user,
            result.durability_loss,
        )

        self.user_repo.save_progress(user)
        if cooldown_duration > 0:
            self.cooldown_repo.set_cooldown(channel_id, twitch_id, cooldown_duration)

        return self.presenter.build_response(user, result)

    def _resolve_cooldown_duration(self, custom_params: dict, is_mod: bool, is_sub: bool) -> int:
        if is_mod:
            return 0

        cooldown_key = GParam.SUBS_FISHING_COOLDOWN if is_sub else GParam.FISHING_COOLDOWN
        return max(int(resolve_param(custom_params, cooldown_key)), 0)

    def _handle_robbery(self, loot: dict, user: UserProgress) -> RobberyResultDTO:
        lookup_range = loot.get("range", 3)
        channel_config = user.channel.config or {}

        victim = self.user_repo.get_rich_victim(
            channel_id=user.channel.id, attacker_id=user.id, lookup_range=lookup_range
        )

        if victim is None:
            return self.engine.calculate_mass_robbery(
                attacker=user,
                victim=None,
                channel_config=channel_config,
                catch=loot,
            )

        locked = self.user_repo.lock_users([user.id, victim.id])
        user = locked[user.id]
        victim = locked[victim.id]
        attacker_modifiers = self.modifier_service.resolve(user, ModifierScope.ROBBERY)
        victim_modifiers = self.modifier_service.resolve(victim, ModifierScope.ROBBERY)

        counter_actions, absorbed = self._apply_robbery_defenses(
            attacker=user,
            victim=victim,
            effects=list(victim_modifiers.effects),
        )

        if absorbed:
            return RobberyResultDTO(
                is_success=False,
                absorbed=True,
                amount_stolen=ZERO_MASS,
                victim_name=victim.username,
                victim_twitch_id=victim.user_twitch_id,
                victim_new_mass=quantize_mass(victim.current_mass),
                chance_used=0.0,
                counter_actions=counter_actions,
            )

        robbery_result = self.engine.calculate_mass_robbery(
            attacker=user,
            victim=victim,
            channel_config=channel_config,
            catch=loot,
            attacker_modifiers=attacker_modifiers.values,
            victim_modifiers=victim_modifiers.values,
            protected_mass_floor=victim_modifiers.mass_floor("robbery"),
        )
        robbery_result.counter_actions = counter_actions

        if robbery_result.is_success:
            requested_stolen = max(
                quantize_mass(robbery_result.amount_stolen),
                ZERO_MASS,
            )
            victim_previous_mass = max(quantize_mass(victim.current_mass), ZERO_MASS)
            applied_stolen = quantize_mass(min(requested_stolen, victim_previous_mass))

            user.current_mass = quantize_mass(quantize_mass(user.current_mass) + applied_stolen)
            user.total_mass_stat = quantize_mass(
                quantize_mass(user.total_mass_stat) + applied_stolen
            )

            victim.current_mass = max(
                quantize_mass(victim_previous_mass - applied_stolen),
                ZERO_MASS,
            )

            robbery_result.amount_stolen = applied_stolen
            robbery_result.victim_new_mass = victim.current_mass
            self.user_repo.save_progress(victim)

        return robbery_result

    def _apply_robbery_defenses(
        self,
        attacker: UserProgress,
        victim: UserProgress,
        effects: list[dict],
    ) -> tuple[list[dict], bool]:
        actions: list[dict] = []
        absorbed = False
        inventory_repo = InventoryRepository(self.user_repo.db)
        for effect in effects:
            if effect.get("type") not in {"absorb_robbery", "robbery_counter"}:
                continue
            if random.random() >= float(effect.get("chance", 1)):
                continue
            durability_cost = int(effect.get("durability_cost", 0))
            source_slot = str(effect.get("source_slot") or "defense")
            if durability_cost:
                inventory_repo.consume_durability(victim.id, source_slot, durability_cost)

            if effect.get("type") == "absorb_robbery":
                absorbed = True
                mass_delta = quantize_mass(effect.get("attacker_mass_delta", 0))
                previous_mass = quantize_mass(attacker.current_mass)
                attacker.current_mass = max(
                    quantize_mass(previous_mass + mass_delta),
                    ZERO_MASS,
                )
                applied = quantize_mass(attacker.current_mass - previous_mass)
                if applied:
                    actions.append(
                        {
                            "type": "add_mass",
                            "amount": str(applied),
                            "message": effect.get("message", ""),
                        }
                    )
                continue

            action = dict(effect.get("action") or {})
            if action.get("type") == "timeout":
                actions.append(
                    {
                        "type": "timeout",
                        "duration_seconds": int(action["duration_seconds"]),
                        "reason": action.get("reason", "Robbery counter"),
                        "message": action.get("message", ""),
                    }
                )
            elif action.get("type") == "add_mass":
                previous_mass = quantize_mass(attacker.current_mass)
                attacker.current_mass = max(
                    quantize_mass(previous_mass + quantize_mass(action.get("mass", 0))),
                    ZERO_MASS,
                )
                actions.append(
                    {
                        "type": "add_mass",
                        "amount": str(quantize_mass(attacker.current_mass - previous_mass)),
                        "message": action.get("message", ""),
                    }
                )
        return actions, absorbed

    def get_profile_stats(
        self, twitch_id: str, channel_id: str, username: str | None = None
    ) -> FishStatsResponse:
        user = self.user_repo.get_progress(twitch_id, channel_id)
        if not user:
            return FishStatsResponse(
                success=False,
                chat_message=resolve_message(
                    {}, MsgKey.ERR_NO_PROFILE, username=username or twitch_id
                ),
                stats={
                    "level": 1,
                    "xp": 0,
                    "xp_to_next_level": 100,
                    "current_mass": ZERO_MASS,
                    "total_fish_stat": 0,
                    "rod_name": "No rod equipped",
                    "luck_bonus": 0.0,
                    "resist_bonus": 0.0,
                    "xp_bonus_pct": 0.0,
                    "rank": 0,
                    "total_mass_stat": ZERO_MASS,
                },
            )

        stats = calculate_player_stats(user)
        channel_config = user.channel.config or {}
        custom_params = channel_config.get("custom_params", {})
        xp_base = int(resolve_param(custom_params, GParam.XP_BASE))
        xp_exponent = float(resolve_param(custom_params, GParam.XP_EXPONENT))
        xp_required = calculate_xp_required(stats["level"], base=xp_base, exponent=xp_exponent)
        stats["xp_to_next_level"] = max(int(xp_required), 0)

        rank = self.user_repo.get_user_rank(user.channel_id, user.id)
        stats["rank"] = rank

        chat_message = resolve_message(
            channel_config,
            MsgKey.PROFILE_STATS_DETAILED,
            username=user.username,
            level=stats["level"],
            xp=stats["xp"],
            xp_next=stats["xp_to_next_level"],
            rod_name=stats["rod_name"],
            luck_fmt=format_percent_signed(stats["luck_bonus"]),
            resist_fmt=format_percent_signed(stats["resist_bonus"]),
            xp_fmt=format_percent_signed(stats["xp_bonus_pct"]),
            current_mass=format_large_number_mass(stats["current_mass"]),
            total_fish_stat=stats["total_fish_stat"],
            rank=rank,
            total_mass=format_large_number_mass(stats["total_mass_stat"]),
        )

        return FishStatsResponse(success=True, chat_message=chat_message, stats=stats)

    def get_channel_top(
        self, channel_id: str, limit: int = 10, mode: str = "current"
    ) -> FishTopResponse:
        mode = (mode or "current").lower()
        top_users = self.user_repo.get_top_users_by_channel(channel_id, limit=limit, mode=mode)
        if not top_users:
            return FishTopResponse(
                success=True, chat_message="No players in leaderboard yet.", top=[], mode=mode
            )

        top_entries = []
        top_lines = []
        for idx, player in enumerate(top_users, start=1):
            total_mass = quantize_mass(player.total_mass_stat)
            current_mass = quantize_mass(player.current_mass)
            total_fish = int(player.total_fish_stat or 0)
            top_entries.append(
                {
                    "rank": idx,
                    "user_twitch_id": player.user_twitch_id,
                    "username": player.username,
                    "level": int(player.level or 1),
                    "xp": int(player.xp or 0),
                    "current_mass": current_mass,
                    "total_fish_stat": total_fish,
                    "total_mass_stat": total_mass,
                }
            )

            if mode == "alltime":
                score_fmt = format_large_number_mass(total_mass)
            elif mode == "catches":
                score_fmt = str(total_fish)
            elif mode == "level":
                score_fmt = f"Lvl {int(player.level or 1)} ({int(player.xp or 0)} XP)"
            else:
                score_fmt = format_large_number_mass(current_mass)

            top_lines.append(f"#{idx} {player.username} ({score_fmt})")

        channel_config = top_users[0].channel.config if top_users[0].channel else {}
        mode_label_map = {
            "alltime": "alltime",
            "catches": "catches",
            "level": "level",
            "current": "current",
        }
        chat_message = resolve_message(
            channel_config or {},
            MsgKey.PROFILE_TOP,
            mode=mode_label_map.get(mode, "current"),
            top_lines=" | ".join(top_lines),
        )
        return FishTopResponse(success=True, chat_message=chat_message, top=top_entries, mode=mode)

    def get_cooldown_status(
        self,
        channel_id: str,
        twitch_id: str,
        username: str,
        is_mod: bool = False,
        is_sub: bool = False,
    ) -> FishCooldownResponse:
        channel = self.user_repo.get_channel(channel_id)
        channel_config = channel.config if channel else {}
        custom_params = (channel_config or {}).get("custom_params", {})
        cooldown_duration = self._resolve_cooldown_duration(custom_params, is_mod, is_sub)
        if channel:
            user = self.user_repo.get_progress(twitch_id, channel_id)
            reduction = (
                self.modifier_service.resolve(user, ModifierScope.FISHING).value(
                    StatKey.COOLDOWN_REDUCTION_PCT
                )
                if user
                else ZERO_MASS
            )
            cooldown_duration = max(
                int(round(cooldown_duration * max(1.0 - float(reduction), 0.0))), 0
            )
        is_active, seconds_left = self.cooldown_repo.check_cooldown(channel_id, twitch_id)
        return self.presenter.build_cooldown_status_response(
            channel_config=channel_config or {},
            username=username,
            cooldown_duration=cooldown_duration,
            cooldown_left=seconds_left,
            is_active=is_active,
        )
