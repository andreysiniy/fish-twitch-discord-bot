"""Record fishing casts into the ledger atomically with the gameplay state."""

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from core.action_types import ActionType
from domain.logic.mass import quantize_mass
from domain.schemas.fishing import FishingResult
from infrastructure.models import RewardPool, UserProgress
from infrastructure.repositories.ruleset_snapshot_repo import RulesetSnapshotRepository
from services.fishing import ruleset_snapshot as snapshot_service
from services.fishing import trace_builder

CAST_STATUS_RESOLVED = "resolved"
CAST_STATUS_FAILED = "failed"
CAST_STATUS_COOLDOWN_REJECTED = "cooldown_rejected"
CAST_STATUS_VALIDATION_REJECTED = "validation_rejected"
MODIFIER_SCHEMA_VERSION = 2


def _trace_value(trace: dict | None, key: str):
    """Extract a key from a WeightedRollResult.as_dict() payload."""
    if not trace or not isinstance(trace, dict):
        return None
    return trace.get(key)


def _stage_by_name(result: FishingResult, stage: str) -> dict | None:
    """Find a traced RNG stage by its stage name."""
    for item in result.rng_stages or []:
        if item.get("stage") == stage:
            return item
    return None


def _decimal_or_none(value) -> Any:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


class FishingLedgerService:
    """Persists resolved/failed casts in the caller's transaction.

    The cast row is added to the same transaction as the gameplay mutations,
    so in strict mode a failed ledger insert rolls back gameplay state.
    """

    def __init__(self, db):
        self.db = db
        self.repo = RulesetSnapshotRepository(db)

    def find_replay(
        self, channel_id: int, source: str, source_request_id: str | None
    ) -> Any | None:
        if not source_request_id:
            return None
        return self.repo.find_cast_by_source_request(channel_id, source, source_request_id)

    def get_or_create_ruleset_snapshot(
        self,
        *,
        user: UserProgress,
        pool: RewardPool | None,
        rewards: list[dict],
        item_entries: list[dict],
        items_drop_rate: float,
        channel_config_version: int,
        event_snapshot: dict,
        effective_params_snapshot: dict,
        engine_version: str,
        item_loot_table_id: int | None = None,
        item_loot_table_version: int | None = None,
    ) -> tuple[str, bool]:
        """Return (snapshot_id, is_new) for the canonical static rules."""
        payload = snapshot_service.build_ruleset_snapshot_payload(
            user=user,
            pool=pool,
            rewards=rewards,
            item_entries=item_entries,
            items_drop_rate=items_drop_rate,
            channel_config_version=channel_config_version,
            modifier_schema_version=MODIFIER_SCHEMA_VERSION,
            engine_version=engine_version,
            event_snapshot=event_snapshot,
            effective_params_snapshot=effective_params_snapshot,
            item_loot_table_id=item_loot_table_id,
            item_loot_table_version=item_loot_table_version,
        )
        ruleset_hash = snapshot_service.snapshot_hash(payload)
        existing = self.repo.find_snapshot_by_hash(user.channel_id, ruleset_hash)
        if existing:
            return existing.id, False
        snapshot = self.repo.create_snapshot(
            channel_id=user.channel_id,
            ruleset_hash=ruleset_hash,
            channel_config_version=channel_config_version,
            location_snapshot=payload["location"],
            reward_entries_snapshot=payload["reward_entries"],
            item_entries_snapshot=payload["item_entries"],
            effective_params_snapshot=payload["effective_params"],
            event_snapshot=payload["event"],
            modifier_schema_version=MODIFIER_SCHEMA_VERSION,
            engine_version=engine_version,
            reward_pool_id=pool.id if pool else None,
            reward_pool_version=pool.version if pool else None,
            item_loot_table_id=item_loot_table_id,
            item_loot_table_version=item_loot_table_version,
            event_id=event_snapshot.get("id") if event_snapshot else None,
            event_version=event_snapshot.get("version") if event_snapshot else None,
        )
        return snapshot.id, True

    def record_resolved(
        self,
        *,
        user: UserProgress,
        result: FishingResult,
        channel_config_version: int,
        event_snapshot: dict,
        effective_params_snapshot: dict,
        engine_version: str,
        source: str = "twitch",
        source_request_id: str | None = None,
        requested_at=None,
        started_at=None,
        is_mod: bool = False,
        is_sub: bool = False,
        bypass_cooldown: bool = False,
        cooldown_seconds_applied: int = 0,
        next_available_at=None,
        ruleset_snapshot_id: str | None = None,
        modifier_explanation: dict | None = None,
        triggered_effects: list | None = None,
        loot_pool: list | None = None,
        item_entries: list | None = None,
        pool_location_id: str | None = None,
        items_drop_rate: float | None = None,
        item_loot_table_id: int | None = None,
        item_loot_table_version: int | None = None,
        duration_ms: int | None = None,
    ) -> Any:
        """Create a resolved cast row. The caller commits the transaction.

        ``result.mass_gained`` is expected to already hold the floored, applied
        delta (as mutated by the fishing service) so ``mass_before`` can be
        recovered as ``current_mass - applied_delta``.
        """
        loot = result.loot or {}
        pool = self._find_pool(user, pool_location_id)
        reward_id = loot.get("reward_id") or loot.get("identifier") or loot.get("id")
        reward_type = loot.get("type")
        applied_delta = quantize_mass(result.mass_gained)
        mass_after = quantize_mass(user.current_mass)
        mass_before = mass_after - applied_delta

        now = datetime.now(timezone.utc)
        started_at = started_at or now
        snapshot_id = ruleset_snapshot_id
        if snapshot_id is None:
            # The whole reward pool that participated in the roll is snapshotted
            # so a later config change can still explain the historic probability.
            snapshot_id = self.get_or_create_ruleset_snapshot(
                user=user,
                pool=pool,
                rewards=loot_pool or (loot and [loot]),
                item_entries=item_entries or [],
                items_drop_rate=items_drop_rate if items_drop_rate is not None else 0.0,
                channel_config_version=channel_config_version,
                event_snapshot=event_snapshot,
                effective_params_snapshot=effective_params_snapshot,
                engine_version=engine_version,
                item_loot_table_id=item_loot_table_id,
                item_loot_table_version=item_loot_table_version,
            )[0]

        explanation = modifier_explanation or {}
        resolved_modifiers = {
            stat: values.get("value")
            for stat, values in explanation.items()
        }
        cast = self.repo.create_cast(
            channel_id=user.channel_id,
            user_progress_id=user.id,
            ruleset_snapshot_id=snapshot_id,
            source=source,
            source_request_id=source_request_id,
            status=CAST_STATUS_RESOLVED,
            twitch_user_id_snapshot=user.user_twitch_id,
            username_snapshot=user.username,
            location_id=user.current_location_id or "default",
            location_name_snapshot=(pool.location_name if pool else None),
            is_mod=is_mod,
            is_sub=is_sub,
            bypass_cooldown=bypass_cooldown,
            event_id=(event_snapshot.get("id") if event_snapshot else None),
            event_title_snapshot=(event_snapshot.get("title") if event_snapshot else None),
            requested_at=requested_at or now,
            started_at=started_at,
            resolved_at=now,
            duration_ms=duration_ms,
            cooldown_seconds_applied=cooldown_seconds_applied,
            next_available_at=next_available_at,
            mass_before=mass_before,
            mass_after=mass_after,
            mass_delta_requested=quantize_mass(result.mass_gained),
            mass_delta_applied=applied_delta,
            xp_before=user.xp - result.xp_gained,
            xp_after=user.xp,
            xp_gained=result.xp_gained,
            level_before=result.old_level,
            level_after=result.new_level,
            points_delta=int(loot.get("value") or 0) if reward_type == ActionType.POINTS else 0,
            was_level_up=result.is_level_up,
            reward_id=reward_id,
            reward_type=reward_type,
            reward_weight=_decimal_or_none(_trace_value(result.reward_roll_trace, "selected_weight")),
            reward_total_weight=_decimal_or_none(_trace_value(result.reward_roll_trace, "total_weight")),
            reward_probability=_decimal_or_none(_trace_value(result.reward_roll_trace, "selected_probability")),
            reward_roll=_decimal_or_none(_trace_value(result.reward_roll_trace, "roll")),
            reward_snapshot=loot,
            item_drop_succeeded=result.item_drop is not None,
            item_drop_count=1 if result.item_drop is not None else 0,
            item_drop_probability=result.item_drop_probability,
            item_drop_roll=result.item_drop_roll,
            item_drop_gate_success=bool(
                _trace_value(
                    _stage_by_name(result, "item_drop_gate"), "success"
                )
            )
            if result.item_drop is not None
            else None,
            item_drop_selection_success=result.item_drop is not None,
            item_drop_stock_reserved=bool(result.item_drop.get("stock_reserved"))
            if result.item_drop is not None
            else None,
            item_drop_grant_success=bool(result.item_drop.get("grant_success"))
            if result.item_drop is not None
            else None,
            resolved_modifiers=json.loads(trace_builder.compact_json(resolved_modifiers)),
            modifier_sources=json.loads(trace_builder.compact_json(explanation)),
            equipped_items_snapshot=trace_builder.build_equipped_items_snapshot(user),
            triggered_effects=json.loads(trace_builder.compact_json(triggered_effects or [])),
            rng_trace=trace_builder.build_rng_trace(result),
            special_result=trace_builder.build_special_result(result),
            result_snapshot=trace_builder.build_result_snapshot(result),
            response_snapshot={},
        )
        self._record_item_drop(cast, result)
        return cast

    def record_rejected(
        self,
        *,
        channel_id: int,
        user_progress_id: int | None,
        twitch_user_id: str,
        username: str,
        location_id: str,
        status: str = CAST_STATUS_COOLDOWN_REJECTED,
        error_code: str | None = None,
        source: str = "twitch",
        source_request_id: str | None = None,
        requested_at=None,
        started_at=None,
    ) -> Any:
        """Append-only rejection row (cooldown/validation) for the ledger.

        Rejected attempts are kept separate from processed casts; they never
        carry RNG outcomes or reward rolls.
        """
        now = datetime.now(timezone.utc)
        started_at = started_at or now
        return self.repo.create_cast(
            channel_id=channel_id,
            user_progress_id=user_progress_id,
            source=source,
            source_request_id=source_request_id,
            status=status,
            error_code=error_code,
            twitch_user_id_snapshot=twitch_user_id,
            username_snapshot=username,
            location_id=location_id,
            requested_at=requested_at or now,
            started_at=started_at,
            resolved_at=now,
        )

    def record_failed(
        self,
        *,
        channel_id: int,
        user_progress_id: int,
        twitch_user_id: str,
        username: str,
        location_id: str,
        error_code: str,
        source: str = "twitch",
        source_request_id: str | None = None,
        requested_at=None,
        started_at=None,
        error_message: str | None = None,
    ) -> Any:
        now = datetime.now(timezone.utc)
        started_at = started_at or now
        return self.repo.create_cast(
            channel_id=channel_id,
            user_progress_id=user_progress_id,
            source=source,
            source_request_id=source_request_id,
            status=CAST_STATUS_FAILED,
            error_code=error_code,
            error_message=error_message,
            twitch_user_id_snapshot=twitch_user_id,
            username_snapshot=username,
            location_id=location_id,
            requested_at=requested_at or now,
            started_at=started_at,
            resolved_at=now,
        )

    def _record_item_drop(self, cast, result: FishingResult) -> None:
        item = result.item_drop
        if not item:
            return
        selection_trace = _stage_by_name(result, "item_selection") or {}
        quantity_requested = int(item.get("quantity_requested") or 0) or int(
            item.get("quantity") or 1
        )
        grant_status = "granted"
        if item.get("grant_success") is False:
            grant_status = "failed"
        elif item.get("stock_reserved") is False:
            grant_status = "stock_empty"
        quantity_granted = int(item.get("quantity_granted") or 0)
        if quantity_granted <= 0:
            quantity_granted = quantity_requested if grant_status == "granted" else 0
        self.repo.add_item_drop(
            cast_id=cast.id,
            channel_id=cast.channel_id,
            item_definition_id=item.get("item_definition_id") or item.get("db_id"),
            item_id_snapshot=item.get("item_id", ""),
            title_snapshot=item.get("title", item.get("item_id", "Unknown Item")),
            rarity_snapshot=item.get("rarity"),
            item_type_snapshot=item.get("item_type"),
            definition_version=item.get("definition_version"),
            loot_table_id=item.get("loot_table_id"),
            loot_table_entry_id=item.get("loot_table_entry_id"),
            selection_weight=_decimal_or_none(
                item.get("selected_weight")
                or _trace_value(selection_trace, "selected_weight")
            ),
            selection_total_weight=_decimal_or_none(
                item.get("total_weight")
                or _trace_value(selection_trace, "total_weight")
            ),
            selection_probability=_decimal_or_none(
                item.get("selection_probability")
                or _trace_value(selection_trace, "selected_probability")
            ),
            selection_roll=_decimal_or_none(
                item.get("selection_roll") or _trace_value(selection_trace, "roll")
            ),
            quantity_requested=quantity_requested,
            quantity_granted=quantity_granted,
            grant_status=grant_status,
            stock_before=item.get("stock_before"),
            stock_after=item.get("stock_after"),
            inventory_grants=item.get("inventory_grants") or [],
            metadata_snapshot={
                key: item[key]
                for key in ("obtained_at", "message", "weight")
                if key in item
            },
        )

    def _find_pool(self, user: UserProgress, location_id: str | None = None) -> RewardPool | None:
        effective_location_id = location_id or (user.current_location_id or "default")
        return (
            self.db.query(RewardPool)
            .filter(
                RewardPool.channel_id == user.channel_id,
                RewardPool.location_id == effective_location_id,
            )
            .first()
        )
