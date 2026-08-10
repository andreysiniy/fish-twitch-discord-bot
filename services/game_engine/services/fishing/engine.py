import random
import time
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Dict, Optional

from core.action_types import ActionType
from core.game_params import GParam, resolve_param
from domain.logic import formulas, rng
from services.loot_table_service import LootTableRollService
from domain.logic.mass import ZERO_MASS, quantize_mass, to_decimal
from domain.logic.stats_calculator import calculate_player_stats
from domain.schemas.fishing import FishingResult, RobberyResultDTO, RussianRouletteResultDTO
from infrastructure.models import UserProgress


def _as_catch(entry: dict) -> Dict[str, Any]:
    """Normalize a traced roll result into the engine's catch dict."""
    return dict(entry)


class CalculationStrategy(ABC):
    @abstractmethod
    def calculate(
        self,
        source: Dict[str, Any],
        luck_modifier: float,
        user_balance: Decimal,
    ) -> Decimal:
        """Calculate resulting mass delta for catch/effect config."""

    def adjust_xp_gain(self, xp_gain: int) -> int:
        return max(int(xp_gain), 0)

    def resolve_raw_mass(
        self, source: Dict[str, Any], user_balance: Decimal
    ) -> Decimal:
        """Unrounded raw mass delta for a catch config (no modifiers, no luck)."""
        return self._resolve_raw_mass(source, to_decimal(user_balance))


class DefaultLootStrategy(CalculationStrategy):
    def calculate(
        self,
        source: Dict[str, Any],
        luck_modifier: float,
        user_balance: Decimal,
    ) -> Decimal:
        raw_mass = self._resolve_raw_mass(source, to_decimal(user_balance))
        return self._apply_luck(raw_mass, luck_modifier)

    def _resolve_raw_mass(self, source: Dict[str, Any], user_balance: Decimal) -> Decimal:
        if source.get("fixed_mass") is not None:
            return to_decimal(source.get("fixed_mass") or 0)

        if source.get("mass") is not None:
            return to_decimal(source.get("mass") or 0)

        if source.get("percentage") is not None:
            percentage = to_decimal(source.get("percentage") or 0)
            return user_balance * percentage

        min_mass = to_decimal(source.get("min_mass", "0.1"))
        max_mass = to_decimal(source.get("max_mass", "5.0"))
        return to_decimal(random.uniform(float(min_mass), float(max_mass)))

    def _apply_luck(self, raw_mass: Decimal, luck_modifier: float) -> Decimal:
        safe_luck = max(
            to_decimal(1 if luck_modifier is None else luck_modifier),
            Decimal("0.01"),
        )
        if raw_mass < 0:
            return quantize_mass(raw_mass / safe_luck)
        return quantize_mass(raw_mass * safe_luck)


class FishingEngine:
    def __init__(self, default_strategy: Optional[CalculationStrategy] = None):
        self._default_strategy = default_strategy or DefaultLootStrategy()

    def calculate_result(
        self,
        user,
        loot_pool,
        item_pool,
        items_drop_rate,
        custom_params,
        calculation_strategy: Optional[CalculationStrategy] = None,
        modifier_values: Optional[Dict[str, Decimal]] = None,
        behavioral_effects: Optional[list[Dict[str, Any]]] = None,
        negative_mass_floor: Decimal = ZERO_MASS,
        roulette_mass_floor: Decimal = ZERO_MASS,
    ) -> FishingResult:
        player_stats = calculate_player_stats(user)
        typed_modifiers = modifier_values is not None
        modifiers = modifier_values or {}
        if typed_modifiers:
            resolved_mods: Dict[str, Decimal] = {
                str(key): to_decimal(value) for key, value in modifiers.items()
            }
        else:
            # Legacy stats path (no resolver): translate the resolved player
            # stats dict into v2 ratio keys so there is a single formula path.
            resolved_mods = {
                "fish_luck_change_ratio": to_decimal(
                    player_stats.get("luck_bonus", 0.0)
                ),
                "positive_fish_reward_change_ratio": to_decimal(
                    player_stats.get("good_catch_bonus", 0.0)
                ),
                "negative_fish_reward_change_ratio": to_decimal(
                    player_stats.get("resolve_bad_catch", 0.0)
                ),
                "xp_gain_change_ratio": to_decimal(
                    player_stats.get("xp_bonus_pct", 0.0)
                ),
                "cooldown_change_ratio": to_decimal(
                    player_stats.get("cd_bonus", 0.0)
                ),
                "item_drop_chance_add": to_decimal(
                    player_stats.get("item_drop_chance_add", 0.0)
                ),
                "item_rarity_luck_pct": to_decimal(
                    player_stats.get("item_rarity_luck_pct", 0.0)
                ),
            }
        fish_luck_ratio = to_decimal(
            resolved_mods.get("fish_luck_change_ratio", 0)
        )
        positive_fish_ratio = to_decimal(
            resolved_mods.get("positive_fish_reward_change_ratio", 0)
        )
        negative_fish_ratio = to_decimal(
            resolved_mods.get("negative_fish_reward_change_ratio", 0)
        )
        fish_luck_factor = max(
            Decimal("0.01"), Decimal("1") + fish_luck_ratio
        )
        positive_fish_factor = max(
            Decimal("0"), Decimal("1") + positive_fish_ratio
        )
        negative_fish_factor = max(
            Decimal("0"), Decimal("1") + negative_fish_ratio
        )
        xp_bonus = to_decimal(resolved_mods.get("xp_gain_change_ratio", 0))
        strategy = calculation_strategy or self._default_strategy

        rng_stages: list[dict] = []
        reward_trace = rng.roll_loot_traced(
            loot_pool,
            weight_transform=lambda entry: rng._default_entry_weight(entry),
        )
        rng_stages.append(
            {
                "stage": "ordinary_reward",
                "algorithm": "weighted_choice_v2",
                "roll": str(reward_trace.roll),
                "total_weight": str(reward_trace.total_weight),
                "selected_reward_id": str(reward_trace.selected_id),
                "selected_probability": str(reward_trace.selected_probability),
            }
        )
        if reward_trace.selected is not None:
            catch = _as_catch(reward_trace.selected)
        else:
            # Neutral selection: fish luck never changes reward probabilities.
            catch = rng.roll_loot(loot_pool)
        empty_reroll_chance = min(
            max(
                to_decimal(modifiers.get("empty_catch_reroll_chance_pct", 0)),
                ZERO_MASS,
            ),
            Decimal("1"),
        )
        if catch.get("type") == ActionType.NOTHING:
            reroll_gate_roll = Decimal(str(random.random()))
            reroll_gate_success = reroll_gate_roll < empty_reroll_chance
            rng_stages.append(
                {
                    "stage": "empty_reward_reroll_gate",
                    "roll": str(reroll_gate_roll),
                    "threshold": str(empty_reroll_chance),
                    "success": reroll_gate_success,
                }
            )
            if reroll_gate_success:
                reroll_trace = rng.roll_loot_traced(
                    loot_pool,
                    weight_transform=lambda entry: rng._default_entry_weight(entry),
                )
                rng_stages.append(
                    {
                        "stage": "empty_reward_reroll",
                        "triggered": True,
                        "roll": str(reroll_trace.roll),
                        "selected_reward_id": str(reroll_trace.selected_id),
                    }
                )
                if reroll_trace.selected is not None:
                    catch = _as_catch(reroll_trace.selected)
                else:
                    # Empty or traced-less pool: fall back to the legacy picker so
                    # injected rolls keep working during tests and migrations.
                    catch = rng.roll_loot(loot_pool)
        catch = self._reroll_reward_effects(
            catch,
            loot_pool,
            behavioral_effects or [],
            rng_stages=rng_stages,
        )
        if catch.get("type") == ActionType.POINTS:
            catch = dict(catch)
            catch["value"] = int(catch.get("value", 0) or 0) + int(
                modifiers.get("points_flat_bonus", player_stats.get("points_bonus", 0)) or 0
            )
        item_catch = None
        item_drop_chance = min(
            max(
                to_decimal(items_drop_rate)
                + to_decimal(resolved_mods.get("item_drop_chance_add", 0)),
                ZERO_MASS,
            ),
            Decimal("1"),
        )
        rarity_luck = Decimal("1") + to_decimal(
            resolved_mods.get("item_rarity_luck_pct", 0)
        )
        item_resolution = None
        item_gate_succeeded = False
        item_drop_probability: Decimal | None = None
        item_drop_roll: Decimal | None = None
        if item_pool:
            gate_roll = Decimal(str(random.random()))
            item_gate_succeeded = gate_roll < item_drop_chance
            item_drop_probability = item_drop_chance
            item_drop_roll = gate_roll
            rng_stages.append(
                {
                    "stage": "item_drop_gate",
                    "roll": str(gate_roll),
                    "threshold": str(item_drop_chance),
                    "success": item_gate_succeeded,
                }
            )
            if item_gate_succeeded:
                item_resolution = LootTableRollService.select(
                    item_pool,
                    rarity_luck=rarity_luck,
                    random_source=random.random,
                )
        if item_pool and item_gate_succeeded and item_resolution is not None:
            item_catch = _as_catch(item_resolution.metadata)
            rng_stages.append(
                {
                    "stage": "item_selection",
                    "roll": str(item_resolution.selection_roll),
                    "total_weight": str(item_resolution.total_weight),
                    "selected_entry_id": str(item_resolution.loot_entry_id),
                    "selected_item_id": item_catch.get("item_id"),
                    "selected_probability": str(
                        item_resolution.selection_probability
                    ),
                }
            )
            base_durability = item_catch.get("max_durability")
            min_quantity = item_resolution.min_quantity
            max_quantity = item_resolution.max_quantity
            quantity = item_resolution.quantity_rolled

            if not item_catch.get("title"):
                item_catch["title"] = item_catch.get("item_id", "Unknown Item")

            item_catch.update(
                {
                    "item_type": item_catch.get("item_type", "collectible"),
                    "quantity": quantity,
                    "quantity_requested": quantity,
                    "current_durability": int(base_durability)
                    if base_durability is not None
                    else None,
                    "obtained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "quantity_rolled": quantity,
                    "selected_weight": str(item_resolution.selected_weight),
                    "total_weight": str(item_resolution.total_weight),
                    "selection_probability": str(
                        item_resolution.selection_probability
                    ),
                    "selection_roll": str(item_resolution.selection_roll),
                    "stock_before": item_resolution.stock_before,
                    "stock_after": item_resolution.stock_after,
                    "quantity_granted": item_resolution.quantity_granted,
                }
            )
            rng_stages.append(
                {
                    "stage": "item_quantity",
                    "quantity": quantity,
                    "min_quantity": min_quantity,
                    "max_quantity": max_quantity,
                }
            )

        base_xp_gain = formulas.calculate_xp_gain(
            base_xp=catch.get("xp", 0),
            item_xp=item_catch.get("xp_gain", 0) if item_catch else 0,
            bonus_pct=xp_bonus,
        )
        xp_gain = strategy.adjust_xp_gain(base_xp_gain)
        xp_without_item = strategy.adjust_xp_gain(
            formulas.calculate_xp_gain(
                base_xp=catch.get("xp", 0),
                item_xp=0,
                bonus_pct=xp_bonus,
            )
        )
        item_xp_gained = max(int(xp_gain) - int(xp_without_item), 0)

        current_xp = user.xp + xp_gain
        old_level = user.level
        new_level = self._calculate_level(current_xp, old_level, custom_params)
        is_levelup = new_level > old_level

        mass_gain = ZERO_MASS
        roulette_result = None
        effective_percentage = None
        if catch.get("type") == ActionType.FISH:
            mass_gain = self._calculate_mass(
                catch,
                quantize_mass(user.current_mass),
                strategy,
                resolved_mods,
                negative_mass_floor,
                rng_stages=rng_stages,
            )
            if catch.get("percentage") is not None:
                raw_percentage = to_decimal(catch.get("percentage"))
                effective_percentage = formulas.apply_fish_reward_modifiers(
                    raw_percentage,
                    fish_luck_ratio,
                    positive_fish_ratio,
                    negative_fish_ratio,
                    round_places=4,
                )
        elif catch.get("type") == ActionType.RUSSIAN_ROULETTE:
            roulette_result = self.calculate_russian_roulette(
                user=user,
                catch=catch,
                luck_modifier=1.0,
                calculation_strategy=strategy,
                modifier_values=resolved_mods,
                mass_floor=roulette_mass_floor,
            )
            if roulette_result.roll is not None:
                rng_stages.append(
                    {
                        "stage": "roulette_hit",
                        "roll": str(roulette_result.roll),
                        "threshold": str(
                            to_decimal(roulette_result.bullets)
                            / max(to_decimal(roulette_result.chambers), Decimal("1"))
                        ),
                        "success": roulette_result.is_hit,
                    }
                )
            mass_gain = roulette_result.mass_delta
            # Roulette percentage outcomes never use fish luck (spec 11.4);
            # the engine still resolves the applied percentage for the presenter.
            outcome = roulette_result.penalty if roulette_result.is_hit else roulette_result.reward
            if isinstance(outcome, dict) and outcome.get("percentage") is not None:
                effective_percentage = formulas.apply_fish_reward_modifiers(
                    to_decimal(outcome.get("percentage")),
                    fish_luck_change_ratio=Decimal("0"),
                    positive_fish_reward_change_ratio=positive_fish_ratio,
                    negative_fish_reward_change_ratio=negative_fish_ratio,
                    round_places=4,
                )

        return FishingResult(
            loot=catch,
            item_drop=item_catch,
            username=user.username,
            xp_gained=xp_gain,
            item_xp_gained=item_xp_gained,
            mass_gained=mass_gain,
            is_level_up=is_levelup,
            old_level=old_level,
            new_level=new_level,
            fish_luck_factor_used=fish_luck_factor,
            positive_fish_factor_used=positive_fish_factor,
            negative_fish_factor_used=negative_fish_factor,
            effective_percentage=effective_percentage,
            item_drop_probability=item_drop_probability,
            item_drop_roll=item_drop_roll,
            roulette_result=roulette_result,
            reward_roll_trace=reward_trace.as_dict(),
            rng_stages=rng_stages,
        )

    def calculate_mass_robbery(
        self,
        attacker: UserProgress,
        victim: UserProgress,
        channel_config: Dict[str, Any],
        catch: Dict,
        attacker_modifiers: Optional[Dict[str, Decimal]] = None,
        victim_modifiers: Optional[Dict[str, Decimal]] = None,
        protected_mass_floor: Decimal = ZERO_MASS,
    ) -> RobberyResultDTO:
        if victim is None:
            return RobberyResultDTO(
                is_success=False,
                victim_found=False,
                amount_stolen=ZERO_MASS,
                victim_name="",
                victim_twitch_id="",
                victim_new_mass=ZERO_MASS,
                chance_used=0.0,
            )
        custom_params = channel_config.get("custom_params", {})
        min_chance = resolve_param(custom_params, GParam.ROB_MIN_CHANCE)
        max_chance = resolve_param(custom_params, GParam.ROB_MAX_CHANCE)
        resist_divisor = resolve_param(custom_params, GParam.ROB_RESIST_DIVISOR)
        loss_divisor = resolve_param(custom_params, GParam.ROB_LOSS_DIVISOR)
        base_rob_chance = resolve_param(custom_params, GParam.ROB_BASE_CHANCE)

        if attacker_modifiers is not None and victim_modifiers is not None:
            victim_mass = max(quantize_mass(victim.current_mass), ZERO_MASS)
            protected_mass = max(
                to_decimal(victim_modifiers.get("protected_mass_flat", 0)),
                to_decimal(protected_mass_floor),
            )
            stealable = max(victim_mass - protected_mass, ZERO_MASS)
            steal_percent = max(to_decimal(catch.get("percentage", 0)), ZERO_MASS)
            steal_value = max(to_decimal(catch.get("mass", 0)), ZERO_MASS)
            base_amount = stealable * steal_percent + steal_value
            final_chance, _, final_amount = formulas.calculate_typed_robbery(
                base_chance=to_decimal(base_rob_chance),
                attacker_chance_add=to_decimal(
                    attacker_modifiers.get("robbery_attack_chance_add", 0)
                ),
                victim_evasion=to_decimal(victim_modifiers.get("robbery_evasion_pct", 0)),
                victim_mass=victim_mass,
                protected_mass=protected_mass,
                base_amount=base_amount,
                attacker_amount_bonus=to_decimal(
                    attacker_modifiers.get("robbery_amount_bonus_pct", 0)
                ),
                victim_protection=to_decimal(
                    victim_modifiers.get("robbery_protection_pct", 0)
                ),
                min_chance=to_decimal(min_chance),
                max_chance=to_decimal(max_chance),
            )
            is_success, roll = rng.calculate_chance_traced(float(final_chance))
            if not is_success:
                final_amount = ZERO_MASS
            return RobberyResultDTO(
                is_success=is_success,
                amount_stolen=final_amount,
                victim_name=victim.username,
                victim_twitch_id=victim.user_twitch_id,
                victim_new_mass=quantize_mass(victim_mass - final_amount),
                chance_used=round(float(final_chance), 3),
                roll=roll,
            )

        attacker_stats = calculate_player_stats(attacker)
        attacker_luck = 1.0 + attacker_stats.get("luck_bonus", 0.0)

        victim_stats = calculate_player_stats(victim)
        victim_resistance = float(victim.level * 5) + (
            float(victim_stats.get("resist_bonus", 0.0) or 0.0) * 100
        )

        final_chance = formulas.calculate_robbery_chance(
            base_chance=base_rob_chance,
            attacker_luck=attacker_luck,
            victim_resistance=victim_resistance,
            resist_divisor=resist_divisor,
            min_chance=min_chance,
            max_chance=max_chance,
        )

        is_success, roll = rng.calculate_chance_traced(float(final_chance))
        victim_mass = max(quantize_mass(victim.current_mass), ZERO_MASS)
        final_amount = ZERO_MASS

        if is_success:
            potential_loss = ZERO_MASS
            steal_percent = max(to_decimal(catch.get("percentage", 0)), ZERO_MASS)
            if steal_percent > 0:
                potential_loss = victim_mass * steal_percent
            steal_value = max(to_decimal(catch.get("mass", 0)), ZERO_MASS)
            if steal_value > 0:
                potential_loss += steal_value

            final_amount = formulas.calculate_robbery_loss(
                potential_loss=potential_loss,
                victim_resistance=victim_resistance,
                loss_divisor=loss_divisor,
            )

            final_amount = quantize_mass(min(final_amount, victim_mass))

        return RobberyResultDTO(
            is_success=is_success,
            amount_stolen=final_amount,
            victim_name=victim.username,
            victim_twitch_id=victim.user_twitch_id,
            victim_new_mass=quantize_mass(victim_mass - final_amount),
            chance_used=round(final_chance, 3),
            roll=roll,
        )

    def calculate_russian_roulette(
        self,
        user: UserProgress,
        catch: Dict[str, Any],
        luck_modifier: float,
        calculation_strategy: Optional[CalculationStrategy] = None,
        modifier_values: Optional[Dict[str, Decimal]] = None,
        mass_floor: Decimal = ZERO_MASS,
    ) -> RussianRouletteResultDTO:
        bullets = max(int(catch.get("bullets", 1)), 0)
        chambers = max(int(catch.get("chambers", 6)), 1)
        is_hit, roulette_roll = rng.is_russian_roulette_hit_traced(
            bullets=bullets, chambers=chambers
        )

        message = catch.get("shot_message" if is_hit else "safe_message")
        if not message:
            message = "BANG!" if is_hit else "Click..."

        penalty = catch.get("penalty")
        reward = catch.get("reward")
        effect_conf = penalty if is_hit else reward

        if not is_hit and not effect_conf:
            if "mass" in catch:
                effect_conf = {"type": ActionType.ADD_MASS, "mass": catch.get("mass", 0)}
            elif "percentage" in catch:
                effect_conf = {
                    "type": ActionType.ADD_PERCENTAGE_MASS,
                    "percentage": catch.get("percentage", 0),
                }

        strategy = calculation_strategy or self._default_strategy
        mass_delta = self._calculate_roulette_mass_delta(
            effect_conf,
            quantize_mass(user.current_mass),
            luck_modifier,
            strategy,
            modifier_values,
            mass_floor,
        )

        return RussianRouletteResultDTO(
            is_hit=is_hit,
            bullets=bullets,
            chambers=chambers,
            roll=roulette_roll,
            message=message,
            mass_delta=mass_delta,
            penalty=penalty,
            reward=reward,
        )

    def _calculate_level(
        self,
        current_xp: int,
        user_level: int,
        custom_params: Dict[str, Any],
    ) -> int:
        xp_exponent = resolve_param(custom_params, GParam.XP_EXPONENT)
        xp_base = resolve_param(custom_params, GParam.XP_BASE)
        level = user_level
        while level < 10_000 and formulas.is_level_up(
            current_xp,
            level,
            base=xp_base,
            exponent=xp_exponent,
        ):
            level += 1
        return level

    def calculate_level(
        self,
        current_xp: int,
        user_level: int,
        custom_params: Dict[str, Any],
    ) -> int:
        """Public level calculation for delivery-aware XP corrections.

        The fishing service recalculates the level after a failed item grant
        zeroes the item XP, so a level-up caused only by an undelivered item
        is never granted.
        """
        return self._calculate_level(current_xp, user_level, custom_params or {})

    def _calculate_mass(
        self,
        catch: Dict[str, Any],
        user_balance: Decimal,
        strategy: CalculationStrategy,
        resolved_mods: Dict[str, Decimal],
        mass_floor: Decimal = ZERO_MASS,
        rng_stages: list[dict] | None = None,
    ) -> Decimal:
        if (
            catch.get("fixed_mass") is None
            and catch.get("mass") is None
            and catch.get("percentage") is None
        ):
            # Roll the mass range here so the exact value is traceable in the
            # ledger; the strategy consumes the pre-rolled value as fixed_mass.
            min_mass = to_decimal(catch.get("min_mass", "0.1"))
            max_mass = to_decimal(catch.get("max_mass", "5.0"))
            rolled_mass = random.uniform(float(min_mass), float(max_mass))
            if rng_stages is not None:
                rng_stages.append(
                    {
                        "stage": "mass_range",
                        "roll": str(to_decimal(rolled_mass)),
                        "min": str(min_mass),
                        "max": str(max_mass),
                    }
                )
            catch = dict(catch)
            catch["fixed_mass"] = to_decimal(rolled_mass)
        raw_delta = strategy.resolve_raw_mass(catch, user_balance)
        return formulas.apply_fish_reward_modifiers(
            raw_delta,
            fish_luck_change_ratio=to_decimal(
                resolved_mods.get("fish_luck_change_ratio", 0)
            ),
            positive_fish_reward_change_ratio=to_decimal(
                resolved_mods.get("positive_fish_reward_change_ratio", 0)
            ),
            negative_fish_reward_change_ratio=to_decimal(
                resolved_mods.get("negative_fish_reward_change_ratio", 0)
            ),
            mass_floor=mass_floor,
            user_balance=user_balance,
        )

    def _calculate_roulette_mass_delta(
        self,
        effect_conf: Optional[Dict[str, Any]],
        user_balance: Decimal,
        luck_modifier: float,
        strategy: CalculationStrategy,
        modifier_values: Optional[Dict[str, Decimal]] = None,
        mass_floor: Decimal = ZERO_MASS,
    ) -> Decimal:
        if not isinstance(effect_conf, dict):
            return ZERO_MASS

        effect_type = str(effect_conf.get("type", "")).lower()
        source: Optional[Dict[str, Decimal]] = None
        if effect_type in {ActionType.ADD_MASS.value, "mass", "add_mass"}:
            source = {"mass": to_decimal(effect_conf.get("mass", effect_conf.get("value", 0)) or 0)}
        elif effect_type in {
            ActionType.ADD_PERCENTAGE_MASS.value,
            "percentage_mass",
            "add_percentage_mass",
        }:
            pct = to_decimal(effect_conf.get("percentage", effect_conf.get("value", 0)) or 0)
            source = {"percentage": pct}

        if source is None:
            return ZERO_MASS

        if modifier_values is None:
            # Legacy path: the strategy fully owns the math (v1 formula).
            return strategy.calculate(source, luck_modifier, user_balance)
        raw_delta = strategy.resolve_raw_mass(source, user_balance)
        # Roulette never uses fish luck (spec 11.4); positive/negative fish
        # change ratios keep applying to keep legacy outcome behavior stable.
        return formulas.apply_fish_reward_modifiers(
            raw_delta,
            fish_luck_change_ratio=Decimal("0"),
            positive_fish_reward_change_ratio=to_decimal(
                modifier_values.get("positive_fish_reward_change_ratio", 0)
                if modifier_values
                else 0
            ),
            negative_fish_reward_change_ratio=to_decimal(
                modifier_values.get("negative_fish_reward_change_ratio", 0)
                if modifier_values
                else 0
            ),
            mass_floor=mass_floor,
            user_balance=user_balance,
        )

    @staticmethod
    def _reroll_reward_effects(
        catch: Dict[str, Any],
        loot_pool: list[Dict[str, Any]],
        effects: list[Dict[str, Any]],
        rng_stages: list[dict] | None = None,
    ) -> Dict[str, Any]:
        current = catch
        for effect in effects:
            effect_type = effect.get("type")
            if effect_type not in {"reroll_reward", "block_action"}:
                continue
            if (
                effect_type == "block_action"
                and effect.get("trigger") != "after_reward_roll"
            ):
                continue
            targets = set(effect.get("target_action_types") or [])
            triggered = 0
            max_rerolls = int(effect.get("max_rerolls", 1))
            for _ in range(max_rerolls):
                if str(current.get("type")) not in targets:
                    break
                if effect_type == "block_action":
                    gate_roll = Decimal(str(random.random()))
                    gate_chance = max(to_decimal(effect.get("chance", 1)), ZERO_MASS)
                    if rng_stages is not None:
                        rng_stages.append(
                            {
                                "stage": "behavioral_block_action_gate",
                                "effect_type": str(effect.get("source_key") or effect_type),
                                "roll": str(gate_roll),
                                "threshold": str(gate_chance),
                                "success": gate_roll < gate_chance,
                            }
                        )
                    if gate_roll >= gate_chance:
                        break
                # Rerolls keep neutral reward-selection luck (spec 3.3).
                rerolled = rng.roll_loot_traced(
                    loot_pool,
                    weight_transform=lambda entry: rng._default_entry_weight(entry),
                )
                if rng_stages is not None:
                    rng_stages.append(
                        {
                            "stage": "behavioral_reward_reroll",
                            "effect_type": str(effect.get("source_key") or effect_type),
                            "roll": str(rerolled.roll),
                            "selected_reward_id": str(rerolled.selected_id),
                        }
                    )
                current = _as_catch(rerolled.selected) if rerolled.selected is not None else current
                triggered += 1
            if triggered:
                effect["_trigger_count"] = triggered
        return current
