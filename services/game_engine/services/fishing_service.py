import logging
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from core import metrics as metrics_module
from core.action_types import ActionType
from core.config import settings
from core.game_params import GParam, resolve_param
from core.messages import MsgKey, format_large_number_mass, resolve_message
from core.version import ENGINE_VERSION
from domain.item_schema import ModifierScope, StatKey
from domain.logic.loot_selection import ItemDropResolution
from domain.logic.formulas import calculate_xp_required


from domain.logic.mass import ZERO_MASS, apply_mass_mutation, quantize_mass, to_decimal
from domain.logic.stats_calculator import calculate_player_stats
from domain.schemas.fishing import (
    FishCooldownResponse,
    FishResponse,
    FishStatsResponse,
    FishTopResponse,
    RobberyResultDTO,
)
from infrastructure.after_commit import schedule_after_commit
from infrastructure.database import SessionLocal
from infrastructure.models import FishingCast, LootTable, RewardPool, UserProgress
from infrastructure.repositories import ChannelRepository, ConfigRepository, UserRepository
from infrastructure.repositories.cooldown_repo import CooldownRepository
from infrastructure.repositories.inventory_overflow_repo import InventoryOverflowRepository
from infrastructure.repositories.inventory_repo import InventoryRepository
from services.fishing.engine import FishingEngine
from services.fishing.ledger_service import FishingLedgerService
from services.fishing.presenter import FishingPresenter
from services.fishing.strategy_resolver import FishingStrategyResolver
from services.loot_table_service import LootTableRollService
from services.player_modifier_service import PlayerModifierService

logger = logging.getLogger(__name__)

def _bonus_segment(emoji: str, label: str, percent_value) -> str:
    """One '🍀 Label: +N% | ' segment, or empty when the stat is zero.

    Zero-valued bonus stats are omitted from the stats line so the channel
    owner does not see a wall of +0% entries; mass is never a bonus segment.
    The value is already percentage points (5 means 5%).
    """
    try:
        value = Decimal(str(percent_value))
    except Exception:
        return ""
    if value == 0:
        return ""
    text = f"{abs(value):.2f}".rstrip("0").rstrip(".")
    sign = "+" if value >= 0 else "-"
    return f"{emoji} {label}: {sign}{text}% | "


def _without_timeout_rewards(loot_pool: list[dict]) -> list[dict]:
    """Drop timeout rewards for channel moderators.

    A moderator cannot be timed out, so the timeout reward is excluded from
    their pool; a pool that becomes empty falls back to a neutral catch so the
    weighted roll never sees an empty table.
    """
    def contains_timeout(reward: dict) -> bool:
        if reward.get("type") == ActionType.TIMEOUT:
            return True
        if reward.get("type") != ActionType.RUSSIAN_ROULETTE:
            return False
        return any(
            isinstance(outcome, dict) and outcome.get("type") == ActionType.TIMEOUT
            for outcome in (reward.get("reward"), reward.get("penalty"))
        )

    pool = [reward for reward in loot_pool if not contains_timeout(reward)]
    if not pool:
        return [{"type": "nothing", "weight": 100, "message": "No fish here..."}]
    return pool


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
        self.ledger = FishingLedgerService(user_repo.db)
        self.overflow_repo = InventoryOverflowRepository(user_repo.db)

    def process_cast(
        self,
        twitch_id: str,
        username: str,
        channel_id: str,
        is_mod: bool = False,
        is_sub: bool = False,
        bypass_cooldown: bool = False,
        source: str = "twitch",
        source_request_id: str | None = None,
        requested_at: datetime | None = None,
    ):
        started_monotonic = time.monotonic()
        started_at = datetime.now(timezone.utc)
        self.user_repo.acquire_fishing_lock(twitch_id, channel_id)
        user = self.user_repo.get_progress(twitch_id, channel_id, lock=True)
        if not user:
            user = self.user_repo.create(twitch_id, username, channel_id)

        if not source_request_id:
            # Every processed cast must produce a durable UUID row even when
            # the caller does not supply a stable external request key.
            source_request_id = f"internal-{uuid.uuid4()}"

        try:
            return self._process_cast_body(
                user=user,
                twitch_id=twitch_id,
                username=username,
                channel_id=channel_id,
                is_mod=is_mod,
                is_sub=is_sub,
                bypass_cooldown=bypass_cooldown,
                source=source,
                source_request_id=source_request_id,
                requested_at=requested_at,
                started_at=started_at,
                started_monotonic=started_monotonic,
            )
        except Exception as error:
            # Release the advisory and row locks before the failed-cast ledger
            # opens its independent transaction. Otherwise its FK insert can
            # wait forever on the user row locked by this failed request.
            failed_user = {
                "channel_id": user.channel_id,
                "user_progress_id": user.id,
                "twitch_user_id": user.user_twitch_id,
                "username": user.username,
                "location_id": user.current_location_id or "default",
            }
            self.user_repo.db.rollback()
            self._record_failed_cast(
                **failed_user,
                source=source,
                source_request_id=source_request_id,
                requested_at=requested_at or started_at,
                started_at=started_at,
                error=error,
            )
            raise

    def _process_cast_body(
        self,
        *,
        user: UserProgress,
        twitch_id: str,
        username: str,
        channel_id: str,
        is_mod: bool,
        is_sub: bool,
        bypass_cooldown: bool,
        source: str,
        source_request_id: str,
        requested_at: datetime | None,
        started_at: datetime,
        started_monotonic: float,
    ):
        replay = self.ledger.find_replay(user.channel_id, source, source_request_id)
        if replay is not None and replay.response_snapshot:
            try:
                response = FishResponse(**replay.response_snapshot)
                response.is_replayed = True
                metrics_module.count_duplicate_request()
                return response
            except Exception as error:
                # A corrupted stored response must never re-run RNG or mutate
                # game state again: surface a recovery error instead.
                logging.getLogger("fishing.ledger").error(
                    "Replay snapshot corrupted for %s/%s",
                    source,
                    source_request_id,
                    exc_info=error,
                )
                raise ValueError(
                    "The stored replay for this cast is corrupted; "
                    "re-run the command once the cast record is repaired."
                ) from error

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
            Decimal("1")
            + fishing_modifiers.value(StatKey.COOLDOWN_CHANGE_RATIO),
            Decimal("0"),
        )
        cooldown_duration = max(
            int(round(to_decimal(cooldown_duration) * cooldown_multiplier)), 0
        )

        if cooldown_duration > 0:
            is_active, seconds_left = self.cooldown_repo.check_cooldown(channel_id, twitch_id)
            if is_active:
                if settings.FISHING_CAST_LEDGER_ENABLED:
                    try:
                        self.ledger.record_rejected(
                            channel_id=user.channel_id,
                            user_progress_id=user.id,
                            twitch_user_id=twitch_id,
                            username=username,
                            location_id=user.current_location_id or "default",
                            status="cooldown_rejected",
                            source=source,
                            source_request_id=source_request_id,
                            requested_at=requested_at,
                            started_at=started_at,
                        )
                    except Exception as error:  # pragma: no cover - defensive
                        if settings.FISHING_CAST_LEDGER_STRICT:
                            raise
                        logging.getLogger("fishing.ledger").warning(
                            "Failed to record cooldown-rejected cast", exc_info=error
                        )
                return self.presenter.build_cooldown_response(
                    user=user, cooldown_duration=cooldown_duration, cooldown_left=seconds_left
                )

        location_id = user.current_location_id or "default"
        cast_mass_before = quantize_mass(user.current_mass)
        loot_pool, item_pool, rate = self.config_repo.get_dual_pool(channel_id, location_id)
        effective_pool_location_id = location_id

        if strategy_ctx.override_loot_pool_location_id is not None:
            override_location_id = str(strategy_ctx.override_loot_pool_location_id).strip()
            if override_location_id:
                override_result = self.config_repo.get_dual_pool(channel_id, override_location_id)
                if override_result:
                    loot_pool, item_pool, rate = override_result
                    effective_pool_location_id = override_location_id

        if is_mod:
            # Channel moderators cannot be timed out by the bot, so the timeout
            # reward must never be selectable while they fish. The weighted roll
            # renormalizes over the remaining entries automatically.
            loot_pool = _without_timeout_rewards(loot_pool)

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
            result.robbery_result = self._handle_robbery(
                result.loot, user, rng_stages=result.rng_stages
            )
            if result.robbery_result.roll is not None:
                result.rng_stages.append(
                    {
                        "stage": "robbery_success",
                        "roll": str(result.robbery_result.roll),
                        "threshold": str(
                            to_decimal(result.robbery_result.chance_used)
                        ),
                        "success": result.robbery_result.is_success,
                    }
                )

        user.xp += result.xp_gained
        user.total_fish_stat += 1

        if result.is_level_up:
            user.level = result.new_level

        if result.mass_gained != 0:
            result.mass_gained = apply_mass_mutation(
                user,
                result.mass_gained,
                mass_floor=fishing_modifiers.mass_floor("negative_rewards"),
                track_total=True,
            )

        if result.item_drop:
            if not result.item_drop.get("title"):
                result.item_drop["title"] = result.item_drop.get("item_id", "Unknown Item")
            if result.item_drop.get("quantity") is None:
                result.item_drop["quantity"] = 1

            quantity_requested = max(
                int(result.item_drop.get("quantity_requested") or 0) or 1,
                1,
            )
            resolution = result.item_drop_resolution
            if resolution is not None:
                loot_service = LootTableRollService(self.user_repo.db)
                resolution.quantity_requested = quantity_requested
                resolution = loot_service.reserve(resolution)
                ok = resolution.status != "stock_empty"
                before = resolution.stock_before
                after = resolution.stock_after
                reserved = resolution.quantity_granted
            else:
                ok, before, after, reserved = self.config_repo.reserve_loot_table_entry_stock(
                    result.item_drop.get("loot_table_entry_id")
                    or result.item_drop.get("db_id"),
                    quantity_requested,
                )
                # Compatibility adapter for a manually constructed legacy
                # result. Runtime loot-table paths always create this typed
                # resolution in FishingEngine before reaching delivery.
                resolution = ItemDropResolution(
                    loot_table_id=result.item_drop.get("loot_table_id"),
                    loot_entry_id=(
                        result.item_drop.get("loot_table_entry_id")
                        or result.item_drop.get("db_id")
                    ),
                    item_definition_id=result.item_drop.get("item_definition_id"),
                    item_id=str(result.item_drop.get("item_id") or ""),
                    title=str(result.item_drop.get("title") or "Unknown Item"),
                    quantity_rolled=quantity_requested,
                    quantity_requested=quantity_requested,
                    quantity_granted=reserved if ok else 0,
                    stock_before=before,
                    stock_after=after,
                    status="selected" if ok else "stock_empty",
                    failure_reason=None if ok else "entry stock exhausted",
                    metadata=dict(result.item_drop),
                )
                result.item_drop_resolution = resolution
                loot_service = LootTableRollService(self.user_repo.db)
            result.item_drop["stock_reserved"] = ok
            result.item_drop["stock_before"] = before
            result.item_drop["stock_after"] = after
            result.item_drop["quantity_requested"] = quantity_requested
            result.item_drop["quantity_granted"] = reserved if ok else 0
            result.item_drop["grant_success"] = False
            if ok and reserved > 0:
                # obtained_at is volatile per-cast metadata; keeping it in the
                # stack meta would prevent identical stackable items dropped at
                # different times from merging.
                item_meta = dict(result.item_drop.get("meta") or {})
                resolution, _ = loot_service.deliver(
                    user,
                    resolution,
                    inventory_repo=InventoryRepository(
                        self.user_repo.db,
                        max_slots_add=self.modifier_service.inventory_slot_bonus(user),
                    ),
                    overflow_repo=self.overflow_repo,
                    source_type="fishing_cast",
                    source_id=source_request_id,
                    grant_overrides={
                        "current_durability": result.item_drop.get("current_durability"),
                        "meta": item_meta,
                    },
                )
                result.item_drop["inventory_grants"] = resolution.inventory_grants
                result.item_drop["grant_success"] = resolution.status in {
                    "granted",
                    "overflowed",
                }
                result.item_drop["quantity"] = resolution.quantity_granted
                if resolution.status == "overflowed":
                    result.item_drop["overflowed"] = True
            else:
                if resolution is not None:
                    resolution.status = "stock_empty"
                    resolution.failure_reason = "entry stock exhausted"
                result.item_drop = None

        if result.item_drop is None or not result.item_drop.get("grant_success"):
            self._strip_undelivered_item_xp(result, user, custom_params)

        inventory_repo = InventoryRepository(self.user_repo.db)
        for effect in behavioral_effects:
            trigger_count = int(effect.pop("_trigger_count", 0))
            effect_type = effect.get("type")
            if effect_type == "consume_durability":
                trigger = effect.get("trigger")
                should_consume = (
                    trigger == "after_cast"
                    or (
                        trigger == "after_successful_cast"
                        and result.loot.get("type") != ActionType.NOTHING
                    )
                    or (trigger == "after_item_drop" and result.item_drop is not None)
                )
                durability_cost = int(effect.get("amount", 1)) if should_consume else 0
            elif effect_type == "consume_charge":
                logger.warning(
                    "consume_charge effect resolved in fishing behavior",
                    extra={"effect": effect},
                )
                continue
            else:
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

        # Robbery applies the transfer inside ``_handle_robbery`` because it
        # must lock and update both participants atomically.  The generic mass
        # mutation above therefore has no robbery delta to record.  Capture
        # the actual net change after all robbery effects (including counters)
        # so the cast journal reflects the state that was committed.
        if result.robbery_result is not None:
            result.mass_gained = quantize_mass(user.current_mass - cast_mass_before)

        self.user_repo.save_progress(user)
        if cooldown_duration > 0:
            # The cooldown cache must not be written before the PostgreSQL
            # transaction commits: a rolled-back cast would otherwise leave a
            # Redis-only cooldown for a cast that never became durable (plan
            # section 16). Defer the cache write until the commit succeeds.
            if not schedule_after_commit(
                self.user_repo.db,
                lambda: self.cooldown_repo.set_cooldown(
                    channel_id, twitch_id, cooldown_duration
                ),
            ):
                logger.warning(
                    "No after-commit hook on session; fishing cooldown not cached",
                    extra={"channel_id": channel_id, "user_id": twitch_id},
                )

        response = self.presenter.build_response(user, result)
        cast_duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        cast = self._record_resolved_cast(
            user=user,
            result=result,
            custom_params=custom_params,
            is_mod=is_mod,
            is_sub=is_sub,
            bypass_cooldown=bypass_cooldown,
            cooldown_duration=cooldown_duration,
            source=source,
            source_request_id=source_request_id,
            requested_at=requested_at,
            started_at=started_at,
            modifier_explanation=fishing_modifiers.explain(),
            triggered_effects=behavioral_effects,
            loot_pool=loot_pool,
            item_pool=item_pool,
            pool_location_id=effective_pool_location_id,
            items_drop_rate=rate,
            duration_ms=cast_duration_ms,
        )
        metrics_module.record_cast_duration(cast_duration_ms / 1000)
        if result.item_drop_resolution is not None:
            resolution = result.item_drop_resolution
            metrics_module.count_item_drop(
                str(resolution.item_id or "unknown"), resolution.status
            )
        if cast is not None:
            response.cast_id = str(cast.id)
            cast.response_snapshot = response.model_dump(mode="json")
            metrics_module.count_cast(
                status="resolved", reward_type=str(result.loot.get("type"))
            )
            logging.getLogger("fishing.cast").info(
                "fishing_cast_recorded",
                extra={
                    "fishing_cast": {
                        "cast_id": str(cast.id),
                        "channel_id": user.channel_id,
                        "user_progress_id": user.id,
                        "source_request_id": source_request_id,
                        "stage": "resolved",
                        "status": "resolved",
                        "reward_type": str(result.loot.get("type")),
                    }
                },
            )
        return response

    def _strip_undelivered_item_xp(self, result, user: UserProgress, custom_params: dict) -> None:
        """Zero the item XP when a selected drop was not actually delivered.

        The engine adds item XP to ``result.xp_gained`` before delivery is
        confirmed (plan section 9). Once a grant fails, the item XP is removed
        from the cast and the level is recalculated so a level-up caused only by
        the undelivered item is never granted.
        """
        item_xp = int(getattr(result, "item_xp_gained", 0) or 0)
        if item_xp <= 0:
            return
        result.xp_gained = max(result.xp_gained - item_xp, 0)
        user.xp = max(user.xp - item_xp, 0)
        recomputed_level = self.engine.calculate_level(
            user.xp, result.old_level, custom_params or {}
        )
        result.new_level = recomputed_level
        result.is_level_up = recomputed_level > result.old_level
        user.level = recomputed_level

    def _record_failed_cast(
        self,
        *,
        channel_id: int,
        user_progress_id: int,
        twitch_user_id: str,
        username: str,
        location_id: str,
        source: str,
        source_request_id: str,
        requested_at: datetime,
        started_at: datetime,
        error: Exception,
    ) -> None:
        """Persist a failed cast row in its own transaction.

        The gameplay transaction rolls back when an unexpected error occurs, so
        the failed row is committed separately to keep the ledger complete.
        """
        if not settings.FISHING_CAST_LEDGER_ENABLED:
            return
        ledger_logger = logging.getLogger("fishing.ledger")
        try:
            failed_db = SessionLocal()
            try:
                ledger = FishingLedgerService(failed_db)
                ledger.record_failed(
                    channel_id=channel_id,
                    user_progress_id=user_progress_id,
                    twitch_user_id=twitch_user_id,
                    username=username,
                    location_id=location_id,
                    error_code=type(error).__name__,
                    source=source,
                    source_request_id=source_request_id,
                    requested_at=requested_at,
                    started_at=started_at,
                    error_message=str(error)[:500],
                )
                failed_db.commit()
            finally:
                failed_db.close()
        except Exception as log_error:  # pragma: no cover - defensive
            if settings.FISHING_CAST_LEDGER_STRICT:
                ledger_logger.error(
                    "Failed to record failed cast %s/%s",
                    source,
                    source_request_id,
                    exc_info=log_error,
                )
            else:
                ledger_logger.warning(
                    "Failed to record failed cast %s/%s",
                    source,
                    source_request_id,
                    exc_info=log_error,
                )

    def _record_resolved_cast(
        self,
        *,
        user: UserProgress,
        result,
        custom_params: dict,
        is_mod: bool,
        is_sub: bool,
        bypass_cooldown: bool,
        cooldown_duration: int,
        source: str,
        source_request_id: str,
        requested_at: datetime | None = None,
        started_at: datetime | None = None,
        modifier_explanation: dict | None = None,
        triggered_effects: list | None = None,
        loot_pool: list | None = None,
        item_pool: list | None = None,
        pool_location_id: str | None = None,
        items_drop_rate: float | None = None,
        duration_ms: int | None = None,
    ) -> "FishingCast | None":
        if not settings.FISHING_CAST_LEDGER_ENABLED:
            return None
        try:
            event = self.strategy_resolver.channel_repo.get_active_fishing_event(user.channel_id)
            event_snapshot = (
                {
                    "id": event.id,
                    "title": event.event_title,
                    "version": event.version,
                }
                if event
                else {}
            )
            effective_params = dict(custom_params or {})
            cooldown_started_at = started_at or requested_at or datetime.now(timezone.utc)
            next_available = (
                cooldown_started_at + timedelta(seconds=cooldown_duration)
                if not bypass_cooldown and cooldown_duration > 0
                else None
            )
            item_loot_table_id = None
            item_loot_table_version = None
            # The pool used for the roll may differ from the user's current
            # location when an event overrides the loot pool; resolve the
            # version snapshot against the effective pool location.
            effective_location_id = pool_location_id or (user.current_location_id or "default")
            pool = (
                self.user_repo.db.query(RewardPool)
                .filter(
                    RewardPool.channel_id == user.channel_id,
                    RewardPool.location_id == effective_location_id,
                )
                .first()
            )
            if pool is not None and pool.item_loot_table_id is not None:
                item_loot_table_id = pool.item_loot_table_id
                table = (
                    self.user_repo.db.query(LootTable)
                    .filter(LootTable.id == item_loot_table_id)
                    .first()
                )
                item_loot_table_version = table.version if table else None
            cast = self.ledger.record_resolved(
                user=user,
                result=result,
                channel_config_version=user.channel.config_version,
                event_snapshot=event_snapshot,
                effective_params_snapshot=effective_params,
                engine_version=ENGINE_VERSION,
                source=source,
                source_request_id=source_request_id,
                requested_at=requested_at,
                started_at=started_at,
                is_mod=is_mod,
                is_sub=is_sub,
                bypass_cooldown=bypass_cooldown,
                cooldown_seconds_applied=cooldown_duration,
                next_available_at=next_available,
                modifier_explanation=modifier_explanation,
                triggered_effects=triggered_effects,
                loot_pool=loot_pool or [],
                item_entries=item_pool or [],
                pool_location_id=effective_location_id,
                items_drop_rate=items_drop_rate,
                item_loot_table_id=item_loot_table_id,
                item_loot_table_version=item_loot_table_version,
                duration_ms=duration_ms,
            )
            cast.rng_trace = result.rng_stages or cast.rng_trace
            return cast
        except Exception as error:  # pragma: no cover - defensive
            metrics_module.count_cast_persist_failure()
            if settings.FISHING_CAST_LEDGER_STRICT:
                raise
            logging.getLogger("fishing.ledger").warning(
                "Failed to record fishing cast", exc_info=error
            )
            return None

    def _resolve_cooldown_duration(self, custom_params: dict, is_mod: bool, is_sub: bool) -> int:
        if is_mod:
            return 0

        cooldown_key = GParam.SUBS_FISHING_COOLDOWN if is_sub else GParam.FISHING_COOLDOWN
        return max(int(resolve_param(custom_params, cooldown_key)), 0)

    def _handle_robbery(
        self, loot: dict, user: UserProgress, rng_stages: list | None = None
    ) -> RobberyResultDTO:
        lookup_range = loot.get("range", 3)
        channel_config = user.channel.config or {}
        attacker_modifiers = self.modifier_service.resolve(user, ModifierScope.ROBBERY)

        victim = self.user_repo.get_rich_victim(
            channel_id=user.channel.id, attacker_id=user.id, lookup_range=lookup_range
        )

        if victim is None:
            robbery_result = self.engine.calculate_mass_robbery(
                attacker=user,
                victim=None,
                channel_config=channel_config,
                catch=loot,
            )
            robbery_result.modifier_snapshot = {
                "attacker": self._robbery_modifier_snapshot(attacker_modifiers),
                "victim": self._empty_robbery_modifier_snapshot(),
            }
            return robbery_result

        locked = self.user_repo.lock_users([user.id, victim.id])
        # Keep the caller's attacker object in sync with the row locked for
        # the robbery. The caller saves that original object after this
        # method returns; without this copy, a separate ORM instance could
        # overwrite the credited mass with its stale value.
        attacker = locked[user.id]
        victim = locked[victim.id]
        victim_modifiers = self.modifier_service.resolve(victim, ModifierScope.ROBBERY)
        modifier_snapshot = {
            "attacker": self._robbery_modifier_snapshot(attacker_modifiers),
            "victim": self._robbery_modifier_snapshot(victim_modifiers),
        }

        counter_actions, absorbed = self._apply_robbery_defenses(
            rng_stages=rng_stages,
            attacker=attacker,
            victim=victim,
            effects=list(victim_modifiers.effects),
            attacker_mass_floor=attacker_modifiers.mass_floor("robbery"),
        )

        if absorbed:
            user.current_mass = attacker.current_mass
            user.total_mass_stat = attacker.total_mass_stat
            return RobberyResultDTO(
                is_success=False,
                absorbed=True,
                amount_stolen=ZERO_MASS,
                victim_name=victim.username,
                victim_twitch_id=victim.user_twitch_id,
                victim_new_mass=quantize_mass(victim.current_mass),
                chance_used=0.0,
                counter_actions=counter_actions,
                modifier_snapshot=modifier_snapshot,
            )

        robbery_result = self.engine.calculate_mass_robbery(
            attacker=attacker,
            victim=victim,
            channel_config=channel_config,
            catch=loot,
            attacker_modifiers=attacker_modifiers.values,
            victim_modifiers=victim_modifiers.values,
            protected_mass_floor=victim_modifiers.mass_floor("robbery"),
        )
        robbery_result.counter_actions = counter_actions
        robbery_result.modifier_snapshot = modifier_snapshot

        if robbery_result.is_success:
            success_actions, _absorbed = self._apply_robbery_defenses(
                rng_stages=rng_stages,
                attacker=attacker,
                victim=victim,
                effects=list(victim_modifiers.effects),
                attacker_mass_floor=attacker_modifiers.mass_floor("robbery"),
                trigger="on_robbery_success",
            )
            counter_actions.extend(success_actions)
            robbery_result.counter_actions = counter_actions

            requested_stolen = max(
                quantize_mass(robbery_result.amount_stolen),
                ZERO_MASS,
            )
            protected_mass = victim_modifiers.mass_floor("robbery")
            victim_delta = apply_mass_mutation(
                victim,
                -requested_stolen,
                mass_floor=protected_mass,
                track_total=False,
            )
            applied_stolen = quantize_mass(-victim_delta)
            apply_mass_mutation(attacker, applied_stolen, track_total=True)

            # The lock query may return a distinct ORM instance from the one
            # held by process_cast. Copy the authoritative values back so its
            # final save cannot undo the robbery credit.
            user.current_mass = attacker.current_mass
            user.total_mass_stat = attacker.total_mass_stat

            robbery_result.amount_stolen = applied_stolen
            robbery_result.victim_new_mass = victim.current_mass
            self.user_repo.save_progress(victim)

        # Counter effects can also mutate the locked attacker before the
        # robbery roll. Preserve those changes on the caller's object too.
        user.current_mass = attacker.current_mass
        user.total_mass_stat = attacker.total_mass_stat
        return robbery_result

    @staticmethod
    def _empty_robbery_modifier_snapshot() -> dict[str, object]:
        return {"resolved": {}, "sources": [], "explanation": {}}

    @staticmethod
    def _robbery_modifier_snapshot(resolved) -> dict[str, object]:
        explain = getattr(resolved, "explain", None)
        if callable(explain):
            explanation = explain()
        else:
            explanation = {
                str(stat): {"value": str(value), "contributions": []}
                for stat, value in (getattr(resolved, "values", {}) or {}).items()
            }
        sources = []
        for stat, details in explanation.items():
            for contribution in details.get("contributions", []):
                sources.append({"stat": stat, **contribution})
        return {
            "resolved": {stat: details.get("value") for stat, details in explanation.items()},
            "sources": sources,
            "explanation": explanation,
        }

    def _apply_robbery_defenses(
        self,
        attacker: UserProgress,
        victim: UserProgress,
        effects: list[dict],
        attacker_mass_floor=ZERO_MASS,
        rng_stages: list | None = None,
        trigger: str = "on_robbery_attempt",
    ) -> tuple[list[dict], bool]:
        """Run robbery defense effects for the requested phase.

        Stacking policy is FIRST_TERMINAL_DEFENSE_WINS: the first terminal
        defense (absorb_robbery / block_action) whose roll passes stops the
        iteration, so later defenses neither execute nor consume durability.
        Counters before that point still run. Effects run in stored order;
        an effect without an explicit trigger defaults to ``on_robbery_attempt``.
        """
        actions: list[dict] = []
        absorbed = False
        inventory_repo = InventoryRepository(self.user_repo.db)
        for effect in effects:
            effect_type = effect.get("type")
            if effect_type not in {"absorb_robbery", "robbery_counter", "block_action"}:
                continue
            if (effect.get("trigger") or "on_robbery_attempt") != trigger:
                continue
            if trigger != "on_robbery_attempt" and effect_type in {
                "absorb_robbery",
                "block_action",
            }:
                continue
            if effect_type == "block_action" and "robbery" not in set(
                effect.get("target_action_types") or []
            ):
                continue
            chance = Decimal(str(effect.get("chance", 1)))
            defense_roll = Decimal(str(random.random()))
            if rng_stages is not None:
                rng_stages.append(
                    {
                        "stage": "robbery_defense_gate",
                        "phase": trigger,
                        "effect_type": str(effect.get("source_key") or effect_type),
                        "roll": str(defense_roll),
                        "threshold": str(chance),
                        "success": defense_roll < chance,
                    }
                )
            if defense_roll >= chance:
                continue
            durability_cost = int(effect.get("durability_cost", 0))
            source_slot = str(effect.get("source_slot") or "defense")
            if durability_cost:
                inventory_repo.consume_durability(victim.id, source_slot, durability_cost)

            if effect_type in {"absorb_robbery", "block_action"}:
                # FIRST_TERMINAL_DEFENSE_WINS: later defenses must not run once
                # a terminal defense absorbed the robbery.
                absorbed = True
                applied = apply_mass_mutation(
                    attacker,
                    effect.get("attacker_mass_delta", 0),
                    mass_floor=attacker_mass_floor,
                    track_total=False,
                )
                if applied:
                    actions.append(
                        {
                            "type": "add_mass",
                            "amount": str(applied),
                            "message": effect.get("message", ""),
                        }
                    )
                break

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
                applied = apply_mass_mutation(
                    attacker,
                    action.get("mass", 0),
                    mass_floor=attacker_mass_floor,
                    track_total=False,
                )
                actions.append(
                    {
                        "type": "add_mass",
                        "amount": str(applied),
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
                    "fish_luck_change_percent": Decimal("0"),
                    "positive_fish_reward_change_percent": Decimal("0"),
                    "negative_fish_reward_change_percent": Decimal("0"),
                    "xp_gain_change_percent": Decimal("0"),
                    "cooldown_change_percent": Decimal("0"),
                    "item_drop_chance_add_pp": Decimal("0"),
                    "item_rarity_luck_change_percent": Decimal("0"),
                    "rank": 0,
                    "total_mass_stat": ZERO_MASS,
                },
            )

        stats = calculate_player_stats(user)
        resolved = self.modifier_service.resolve(user, ModifierScope.FISHING)
        stats["fish_luck_change_percent"] = to_decimal(
            resolved.value(StatKey.FISH_LUCK_CHANGE_RATIO) * Decimal("100")
        )
        stats["positive_fish_reward_change_percent"] = to_decimal(
            resolved.value(StatKey.POSITIVE_FISH_REWARD_CHANGE_RATIO) * Decimal("100")
        )
        stats["negative_fish_reward_change_percent"] = to_decimal(
            resolved.value(StatKey.NEGATIVE_FISH_REWARD_CHANGE_RATIO) * Decimal("100")
        )
        stats["xp_gain_change_percent"] = to_decimal(
            resolved.value(StatKey.XP_GAIN_CHANGE_RATIO) * Decimal("100")
        )
        stats["cooldown_change_percent"] = to_decimal(
            resolved.value(StatKey.COOLDOWN_CHANGE_RATIO) * Decimal("100")
        )
        stats["item_drop_chance_add_pp"] = to_decimal(
            resolved.value(StatKey.ITEM_DROP_CHANCE_ADD) * Decimal("100")
        )
        stats["item_rarity_luck_change_percent"] = to_decimal(
            resolved.value(StatKey.ITEM_RARITY_LUCK_PCT) * Decimal("100")
        )
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
            luck_fmt=_bonus_segment(
                "🍀", "Fish Luck", stats["fish_luck_change_percent"]
            ),
            good_catch_fmt=_bonus_segment(
                "🐟", "Good Catch", stats["positive_fish_reward_change_percent"]
            ),
            bad_catch_fmt=_bonus_segment(
                "🛟", "Bad Catch", stats["negative_fish_reward_change_percent"]
            ),
            xp_fmt=_bonus_segment("✨", "XP", stats["xp_gain_change_percent"]),
            cd_fmt=_bonus_segment("⏱", "CD", stats["cooldown_change_percent"]),
            item_drop_fmt=_bonus_segment(
                "📦", "Item Drop", stats["item_drop_chance_add_pp"]
            ),
            item_rarity_fmt=_bonus_segment(
                "💎", "Item Rarity", stats["item_rarity_luck_change_percent"]
            ),
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
            change_ratio = (
                self.modifier_service.resolve(user, ModifierScope.FISHING).value(
                    StatKey.COOLDOWN_CHANGE_RATIO
                )
                if user
                else ZERO_MASS
            )
            cooldown_duration = max(
                int(
                    round(
                        to_decimal(cooldown_duration)
                        * max(Decimal("1") + change_ratio, Decimal("0"))
                    )
                ),
                0,
            )
        is_active, seconds_left = self.cooldown_repo.check_cooldown(channel_id, twitch_id)
        return self.presenter.build_cooldown_status_response(
            channel_config=channel_config or {},
            username=username,
            cooldown_duration=cooldown_duration,
            cooldown_left=seconds_left,
            is_active=is_active,
        )
