import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from domain.item_schema import (
    STAT_REGISTRY,
    ModifierOperation,
    ModifierScope,
    StatKey,
    migrate_stat_key,
)
from domain.modifier_resolver import (
    ModifierContribution,
    PlayerModifierResolver,
    ResolvedStat,
)
from infrastructure.models import EquippedItem, FishingEvent, PlayerModifier, UserProgress
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ResolvedPlayerModifiers:
    scope: ModifierScope
    stats: dict[StatKey, ResolvedStat]
    effects: tuple[dict[str, Any], ...]

    @property
    def values(self) -> dict[str, Decimal]:
        return PlayerModifierResolver.values(self.stats)

    def value(self, stat: StatKey) -> Decimal:
        return self.stats[stat].value

    def explain(self) -> dict[str, dict]:
        return {stat.value: resolved.as_dict() for stat, resolved in self.stats.items()}

    def mass_floor(self, effect_scope: str) -> Decimal:
        floors = [
            Decimal(str(effect["protected_mass"]))
            for effect in self.effects
            if effect.get("type") == "mass_floor"
            and effect_scope in (effect.get("scopes") or [])
        ]
        return max(floors, default=Decimal("0"))


logger = logging.getLogger(__name__)

_EVENT_MODIFIER_BOUNDS = {
    "fish_luck_change_percent": (Decimal("-50"), Decimal("100")),
    "positive_fish_reward_change_percent": (Decimal("-50"), Decimal("200")),
    "negative_fish_reward_change_percent": (Decimal("-100"), Decimal("100")),
    "xp_gain_change_percent": (Decimal("-100"), Decimal("400")),
    "cooldown_change_percent": (Decimal("-80"), Decimal("100")),
    "item_drop_chance_add_pp": (Decimal("-100"), Decimal("100")),
    "item_rarity_luck_change_percent": (Decimal("-100"), Decimal("200")),
    "robbery_protection_percent": (Decimal("0"), Decimal("100")),
    "robbery_evasion_percent": (Decimal("0"), Decimal("100")),
}


def parse_event_modifiers_lenient(
    event_id: int, modifiers: dict
):
    """Parse event modifiers without crashing on legacy out-of-range values.

    Events created before the v2 bounds were tightened may carry values beyond
    the schema caps (e.g. +500% reward). Runtime clamps them to the schema
    bounds and logs the adjustment so fishing and fishstats keep working and
    the owner can fix the event; a hard ValidationError here would 500 every
    cast while the event is active.
    """
    from domain.config_schema import EventModifiersV2

    try:
        return EventModifiersV2(**modifiers)
    except ValidationError:
        clamped: dict[str, Any] = {"schema_version": 2}
        for key, (low, high) in _EVENT_MODIFIER_BOUNDS.items():
            raw = modifiers.get(key)
            if raw is None:
                continue
            try:
                value = Decimal(str(raw))
            except Exception:
                continue
            clamped[key] = min(max(value, low), high)
        logger.warning(
            "Event %s has out-of-range modifiers; clamped to schema bounds",
            event_id,
            extra={
                "event_id": event_id,
                "original": {k: str(v) for k, v in modifiers.items() if k != "schema_version"},
                "clamped": {k: str(v) for k, v in clamped.items() if k != "schema_version"},
            },
        )
        return EventModifiersV2(**clamped)




class PlayerModifierService:
    def __init__(self, db: Session):
        self.db = db
        self.resolver = PlayerModifierResolver()

    def resolve(
        self,
        user: UserProgress,
        scope: ModifierScope,
        event: FishingEvent | None = None,
    ) -> ResolvedPlayerModifiers:
        contributions: list[ModifierContribution] = []
        effects: list[dict[str, Any]] = []
        contributions.extend(self._equipment_contributions(user.id, scope, effects))
        active_event = event or self._active_event(user.channel_id)
        if active_event:
            contributions.extend(self._event_contributions(active_event, scope))
        contributions.extend(self._player_contributions(user, scope))
        stats = self.resolver.resolve(contributions, scope)
        return ResolvedPlayerModifiers(scope=scope, stats=stats, effects=tuple(effects))

    def inventory_slot_bonus(self, user: UserProgress) -> int:
        resolved = self.resolve(user, ModifierScope.INVENTORY)
        return int(resolved.value(StatKey.INVENTORY_SLOTS_ADD))

    def _equipment_contributions(
        self,
        user_id: int,
        scope: ModifierScope,
        behavioral_effects: list[dict[str, Any]],
    ) -> list[ModifierContribution]:
        equipped = (
            self.db.query(EquippedItem)
            .filter(EquippedItem.user_id == user_id)
            .order_by(EquippedItem.slot.asc())
            .all()
        )
        contributions: list[ModifierContribution] = []
        for record in equipped:
            item = record.inventory_item
            definition = item.definition if item else None
            if (
                not item
                or not definition
                or not definition.is_active
                or (item.current_durability is not None and item.current_durability <= 0)
            ):
                continue
            for effect_index, effect in enumerate(definition.effects or []):
                effect_type = str(effect.get("type") or "")
                if effect_type not in {"stat_add", "stat_multiply"}:
                    behavioral_effects.append(
                        {
                            **effect,
                            "source_item_id": item.id,
                            "source_item_key": definition.item_id,
                            "source_slot": record.slot,
                            "source_title": definition.title,
                        }
                    )
                    continue
                stat, effect_value = migrate_stat_key(
                    str(effect["stat"]), Decimal(str(effect["value"]))
                )
                definition_data = STAT_REGISTRY[stat]
                if scope not in definition_data.scopes:
                    continue
                contributions.append(
                    ModifierContribution(
                        stat=stat,
                        operation=(
                            ModifierOperation.ADD
                            if effect_type == "stat_add"
                            else ModifierOperation.MULTIPLY
                        ),
                        value=effect_value,
                        source_type="item",
                        source_key=f"{item.id}:{effect_index}",
                        label=definition.title,
                        scope=scope,
                        priority=100,
                    )
                )
        return contributions

    @staticmethod
    def _event_contributions(
        event: FishingEvent, scope: ModifierScope
    ) -> list[ModifierContribution]:
        if scope != ModifierScope.FISHING:
            return []
        modifiers = event.modifiers or {}
        if modifiers.get("schema_version") == 2:
            return PlayerModifierService._event_contributions_v2(event, scope, modifiers)
        return PlayerModifierService._event_contributions_legacy(event, scope, modifiers)

    @staticmethod
    def _event_contributions_legacy(
        event: FishingEvent, scope: ModifierScope, modifiers: dict
    ) -> list[ModifierContribution]:
        mapped: list[tuple[StatKey, Decimal, str]] = []
        luck_mult = Decimal(str(modifiers.get("luck_mult", 1)))
        xp_mult = Decimal(str(modifiers.get("xp_mult", 1)))
        cooldown_reduction = Decimal(str(modifiers.get("cd_reduction", 0)))
        mass_bonus = Decimal(str(modifiers.get("bonus_mass", 0)))
        mapped.extend(
            [
                (StatKey.FISH_LUCK_CHANGE_RATIO, luck_mult - Decimal("1"), "luck_mult"),
                (StatKey.XP_GAIN_CHANGE_RATIO, xp_mult - Decimal("1"), "xp_mult"),
                (StatKey.COOLDOWN_CHANGE_RATIO, -cooldown_reduction, "cd_reduction"),
                (StatKey.POSITIVE_FISH_REWARD_CHANGE_RATIO, mass_bonus, "bonus_mass"),
            ]
        )
        if mass_bonus > 0:
            mapped.append(
                (
                    StatKey.NEGATIVE_FISH_REWARD_CHANGE_RATIO,
                    -(mass_bonus / (Decimal("1") + mass_bonus)),
                    "bonus_mass",
                )
            )
        return [
            ModifierContribution(
                stat=stat,
                operation=ModifierOperation.ADD,
                value=value,
                source_type="event",
                source_key=f"{event.id}:{key}",
                label=event.event_title,
                scope=scope,
                priority=200,
            )
            for stat, value, key in mapped
            if value != 0
        ]

    @staticmethod
    def _event_contributions_v2(
        event: FishingEvent, scope: ModifierScope, modifiers: dict
    ) -> list[ModifierContribution]:
        payload = parse_event_modifiers_lenient(event.id, modifiers).to_resolver_payload()
        stat_keys = {
            "fish_luck_change_ratio": StatKey.FISH_LUCK_CHANGE_RATIO,
            "positive_fish_reward_change_ratio": StatKey.POSITIVE_FISH_REWARD_CHANGE_RATIO,
            "negative_fish_reward_change_ratio": StatKey.NEGATIVE_FISH_REWARD_CHANGE_RATIO,
            "xp_gain_change_ratio": StatKey.XP_GAIN_CHANGE_RATIO,
            "cooldown_change_ratio": StatKey.COOLDOWN_CHANGE_RATIO,
            "item_drop_chance_add": StatKey.ITEM_DROP_CHANCE_ADD,
            "item_rarity_luck_pct": StatKey.ITEM_RARITY_LUCK_PCT,
            "robbery_protection_pct": StatKey.ROBBERY_PROTECTION_PCT,
            "robbery_evasion_pct": StatKey.ROBBERY_EVASION_PCT,
        }
        contributions: list[ModifierContribution] = []
        for key, stat in stat_keys.items():
            value = Decimal(str(payload[key]))
            if value == 0:
                continue
            contributions.append(
                ModifierContribution(
                    stat=stat,
                    operation=ModifierOperation.ADD,
                    value=value,
                    source_type="event",
                    source_key=f"{event.id}:{key}",
                    label=event.event_title,
                    scope=scope,
                    priority=200,
                )
            )
        return contributions

    def _player_contributions(
        self, user: UserProgress, scope: ModifierScope
    ) -> list[ModifierContribution]:
        now = datetime.now(timezone.utc)
        rows = (
            self.db.query(PlayerModifier)
            .filter(
                PlayerModifier.channel_id == user.channel_id,
                PlayerModifier.user_progress_id == user.id,
                PlayerModifier.is_enabled.is_(True),
                (PlayerModifier.starts_at.is_(None) | (PlayerModifier.starts_at <= now)),
                (PlayerModifier.expires_at.is_(None) | (PlayerModifier.expires_at > now)),
            )
            .order_by(PlayerModifier.id.asc())
            .all()
        )
        contributions: list[ModifierContribution] = []
        for row in rows:
            stat, row_value = migrate_stat_key(row.stat_key, Decimal(row.value))
            row_scope = ModifierScope(row.scope)
            if row_scope not in {scope, ModifierScope.ALL}:
                continue
            if scope not in STAT_REGISTRY[stat].scopes:
                continue
            contributions.append(
                ModifierContribution(
                    stat=stat,
                    operation=ModifierOperation(row.operation),
                    value=row_value,
                    source_type="player_modifier",
                    source_key=row.source_key,
                    label=row.reason,
                    scope=row_scope,
                    priority=300,
                )
            )
        return contributions

    def _active_event(self, channel_id: int) -> FishingEvent | None:
        return (
            self.db.query(FishingEvent)
            .filter(FishingEvent.channel_id == channel_id, FishingEvent.is_active.is_(True))
            .first()
        )
