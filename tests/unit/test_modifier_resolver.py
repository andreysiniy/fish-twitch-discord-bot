from decimal import Decimal

import pytest
from domain.item_schema import ModifierOperation, ModifierScope, StatKey
from domain.modifier_resolver import ModifierContribution, PlayerModifierResolver


def contribution(
    operation: ModifierOperation,
    value: str,
    *,
    priority: int = 0,
) -> ModifierContribution:
    return ModifierContribution(
        stat=StatKey.POSITIVE_MASS_BONUS_PCT,
        operation=operation,
        value=Decimal(value),
        source_type="item",
        source_key=f"source-{priority}-{operation.value}",
        label="Test source",
        scope=ModifierScope.FISHING,
        priority=priority,
    )


def test_resolver_uses_documented_operation_order_and_breakdown() -> None:
    resolved = PlayerModifierResolver().resolve(
        [
            contribution(ModifierOperation.ADD, "0.25"),
            contribution(ModifierOperation.MULTIPLY, "2"),
            contribution(ModifierOperation.MIN, "0.75"),
            contribution(ModifierOperation.MAX, "0.90"),
        ],
        ModifierScope.FISHING,
        {StatKey.POSITIVE_MASS_BONUS_PCT: Decimal("0.10")},
    )[StatKey.POSITIVE_MASS_BONUS_PCT]

    assert resolved.additive_total == Decimal("0.25")
    assert resolved.multiplier == Decimal("2")
    assert resolved.unclamped == Decimal("0.75")
    assert resolved.value == Decimal("0.75")
    assert len(resolved.as_dict()["contributions"]) == 4


def test_override_is_priority_ordered_then_registry_clamped() -> None:
    resolved = PlayerModifierResolver().resolve(
        [
            contribution(ModifierOperation.OVERRIDE, "0.5", priority=10),
            contribution(ModifierOperation.OVERRIDE, "99", priority=20),
        ],
        ModifierScope.FISHING,
    )[StatKey.POSITIVE_MASS_BONUS_PCT]

    assert resolved.override == Decimal("99")
    assert resolved.unclamped == Decimal("99")
    assert resolved.value == Decimal("10")


def test_negative_multiplier_and_conflicting_bounds_are_rejected() -> None:
    with pytest.raises(ValueError, match="multiplier"):
        PlayerModifierResolver().resolve(
            [contribution(ModifierOperation.MULTIPLY, "-1")],
            ModifierScope.FISHING,
        )
    with pytest.raises(ValueError, match="Conflicting"):
        PlayerModifierResolver().resolve(
            [
                contribution(ModifierOperation.MIN, "0.8"),
                contribution(ModifierOperation.MAX, "0.5"),
            ],
            ModifierScope.FISHING,
        )
