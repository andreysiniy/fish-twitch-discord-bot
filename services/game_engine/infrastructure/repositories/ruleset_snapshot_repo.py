from typing import Any
from uuid import UUID as _UUID

from infrastructure.models import FishingCast, FishingCastItemDrop, FishingRulesetSnapshot
from sqlalchemy.orm import Session


class RulesetSnapshotRepository:
    """Persists and deduplicates ruleset snapshots and fishing casts atomically."""

    def __init__(self, db: Session):
        self.db = db

    def find_snapshot_by_hash(self, channel_id: int, ruleset_hash: str) -> FishingRulesetSnapshot | None:
        return (
            self.db.query(FishingRulesetSnapshot)
            .filter(
                FishingRulesetSnapshot.channel_id == channel_id,
                FishingRulesetSnapshot.ruleset_hash == ruleset_hash,
            )
            .first()
        )

    def create_snapshot(
        self,
        *,
        channel_id: int,
        ruleset_hash: str,
        channel_config_version: int,
        location_snapshot: dict,
        reward_entries_snapshot: list,
        item_entries_snapshot: list,
        effective_params_snapshot: dict,
        event_snapshot: dict,
        modifier_schema_version: int,
        engine_version: str,
        reward_pool_id: int | None = None,
        reward_pool_version: int | None = None,
        item_loot_table_id: int | None = None,
        item_loot_table_version: int | None = None,
        event_id: int | None = None,
        event_version: int | None = None,
    ) -> FishingRulesetSnapshot:
        snapshot = FishingRulesetSnapshot(
            channel_id=channel_id,
            ruleset_hash=ruleset_hash,
            channel_config_version=channel_config_version,
            location_snapshot=location_snapshot,
            reward_entries_snapshot=reward_entries_snapshot,
            item_entries_snapshot=item_entries_snapshot,
            effective_params_snapshot=effective_params_snapshot,
            event_snapshot=event_snapshot,
            modifier_schema_version=modifier_schema_version,
            engine_version=engine_version,
            reward_pool_id=reward_pool_id,
            reward_pool_version=reward_pool_version,
            item_loot_table_id=item_loot_table_id,
            item_loot_table_version=item_loot_table_version,
            event_id=event_id,
            event_version=event_version,
        )
        self.db.add(snapshot)
        self.db.flush()
        return snapshot

    def create_cast(self, **fields: Any) -> FishingCast:
        cast = FishingCast(**fields)
        self.db.add(cast)
        self.db.flush()
        return cast

    def add_item_drop(self, **fields: Any) -> FishingCastItemDrop:
        drop = FishingCastItemDrop(**fields)
        self.db.add(drop)
        return drop

    def find_cast_by_source_request(
        self, channel_id: int, source: str, source_request_id: str
    ) -> FishingCast | None:
        if not source_request_id:
            return None
        return (
            self.db.query(FishingCast)
            .filter(
                FishingCast.channel_id == channel_id,
                FishingCast.source == source,
                FishingCast.source_request_id == source_request_id,
            )
            .first()
        )

    def get_cast(self, cast_id: str, channel_id: int) -> FishingCast | None:
        try:
            cast_id = _UUID(str(cast_id))
        except ValueError:
            return None
        return (
            self.db.query(FishingCast)
            .filter(FishingCast.id == cast_id, FishingCast.channel_id == channel_id)
            .first()
        )
