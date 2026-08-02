from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from domain.item_schema import STAT_REGISTRY, ModifierOperation, ModifierScope, StatKey
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
                stat = StatKey(str(effect["stat"]))
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
                        value=Decimal(str(effect["value"])),
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
        mapped: list[tuple[StatKey, Decimal, str]] = []
        luck_mult = Decimal(str(modifiers.get("luck_mult", 1)))
        xp_mult = Decimal(str(modifiers.get("xp_mult", 1)))
        cooldown_reduction = Decimal(str(modifiers.get("cd_reduction", 0)))
        mass_bonus = Decimal(str(modifiers.get("bonus_mass", 0)))
        mapped.extend(
            [
                (StatKey.LOOT_LUCK_PCT, luck_mult - Decimal("1"), "luck_mult"),
                (StatKey.XP_GAIN_BONUS_PCT, xp_mult - Decimal("1"), "xp_mult"),
                (StatKey.COOLDOWN_REDUCTION_PCT, cooldown_reduction, "cd_reduction"),
                (StatKey.POSITIVE_MASS_BONUS_PCT, mass_bonus, "bonus_mass"),
            ]
        )
        if mass_bonus > 0:
            mapped.append(
                (
                    StatKey.NEGATIVE_MASS_REDUCTION_PCT,
                    mass_bonus / (Decimal("1") + mass_bonus),
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
            stat = StatKey(row.stat_key)
            row_scope = ModifierScope(row.scope)
            if row_scope not in {scope, ModifierScope.ALL}:
                continue
            if scope not in STAT_REGISTRY[stat].scopes:
                continue
            contributions.append(
                ModifierContribution(
                    stat=stat,
                    operation=ModifierOperation(row.operation),
                    value=Decimal(row.value),
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
