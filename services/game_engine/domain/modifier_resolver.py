from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from domain.item_schema import (
    STAT_REGISTRY,
    ModifierOperation,
    ModifierScope,
    StatKey,
)


@dataclass(frozen=True)
class ModifierContribution:
    stat: StatKey
    operation: ModifierOperation
    value: Decimal
    source_type: str
    source_key: str
    label: str
    scope: ModifierScope
    priority: int = 0


@dataclass(frozen=True)
class ResolvedStat:
    stat: StatKey
    base: Decimal
    additive_total: Decimal
    multiplier: Decimal
    override: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None
    unclamped: Decimal
    value: Decimal
    contributions: tuple[ModifierContribution, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "stat": self.stat.value,
            "base": str(self.base),
            "additive_total": str(self.additive_total),
            "multiplier": str(self.multiplier),
            "override": str(self.override) if self.override is not None else None,
            "minimum": str(self.minimum) if self.minimum is not None else None,
            "maximum": str(self.maximum) if self.maximum is not None else None,
            "unclamped": str(self.unclamped),
            "value": str(self.value),
            "contributions": [
                {
                    "operation": item.operation.value,
                    "value": str(item.value),
                    "source_type": item.source_type,
                    "source_key": item.source_key,
                    "label": item.label,
                    "scope": item.scope.value,
                    "priority": item.priority,
                }
                for item in self.contributions
            ],
        }


class PlayerModifierResolver:
    def resolve(
        self,
        contributions: Iterable[ModifierContribution],
        scope: ModifierScope,
        base_values: dict[StatKey, Decimal] | None = None,
    ) -> dict[StatKey, ResolvedStat]:
        base_values = base_values or {}
        grouped: dict[StatKey, list[ModifierContribution]] = {stat: [] for stat in StatKey}
        for contribution in contributions:
            self._validate_contribution(contribution, scope)
            if contribution.scope in {scope, ModifierScope.ALL}:
                grouped[contribution.stat].append(contribution)

        resolved: dict[StatKey, ResolvedStat] = {}
        for stat in StatKey:
            definition = STAT_REGISTRY[stat]
            base = Decimal(base_values.get(stat, Decimal("0")))
            entries = sorted(
                grouped[stat],
                key=lambda item: (
                    item.priority,
                    item.source_type,
                    item.source_key,
                    item.operation.value,
                ),
            )
            additive = sum(
                (item.value for item in entries if item.operation == ModifierOperation.ADD),
                Decimal("0"),
            )
            multiplier = Decimal("1")
            for item in entries:
                if item.operation == ModifierOperation.MULTIPLY:
                    multiplier *= item.value
            overrides = [item for item in entries if item.operation == ModifierOperation.OVERRIDE]
            override = overrides[-1].value if overrides else None
            minimums = [item.value for item in entries if item.operation == ModifierOperation.MIN]
            maximums = [item.value for item in entries if item.operation == ModifierOperation.MAX]
            minimum = max(minimums) if minimums else None
            maximum = min(maximums) if maximums else None
            if minimum is not None and maximum is not None and minimum > maximum:
                raise ValueError(f"Conflicting min and max modifiers for {stat.value}")

            value = (base + additive) * multiplier
            if override is not None:
                value = override
            if minimum is not None:
                value = max(value, minimum)
            if maximum is not None:
                value = min(value, maximum)
            unclamped = value
            value = min(max(value, definition.minimum), definition.maximum)
            resolved[stat] = ResolvedStat(
                stat=stat,
                base=base,
                additive_total=additive,
                multiplier=multiplier,
                override=override,
                minimum=minimum,
                maximum=maximum,
                unclamped=unclamped,
                value=value,
                contributions=tuple(entries),
            )
        return resolved

    @staticmethod
    def values(resolved: dict[StatKey, ResolvedStat]) -> dict[str, Decimal]:
        return {stat.value: item.value for stat, item in resolved.items()}

    @staticmethod
    def _validate_contribution(
        contribution: ModifierContribution, requested_scope: ModifierScope
    ) -> None:
        definition = STAT_REGISTRY[contribution.stat]
        if contribution.source_type not in definition.allowed_sources:
            raise ValueError(
                f"Source type '{contribution.source_type}' is not allowed for "
                f"{contribution.stat.value}"
            )
        if requested_scope not in definition.scopes:
            return
        if contribution.scope not in definition.scopes | {ModifierScope.ALL}:
            raise ValueError(
                f"Scope '{contribution.scope.value}' is not allowed for "
                f"{contribution.stat.value}"
            )
        if contribution.operation == ModifierOperation.MULTIPLY and contribution.value < 0:
            raise ValueError("Modifier multiplier must not be negative")
