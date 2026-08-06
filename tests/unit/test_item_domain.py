from decimal import Decimal

import pytest
from domain.item_schema import (
    ItemDefinitionData,
    ModifierScope,
    STAT_REGISTRY,
    StatKey,
)
from domain.schemas.admin import ItemDefinitionCreateDTO
from domain.schemas.discord_admin import PlayerModifierSetRequest
from pydantic import ValidationError


def test_equipment_requires_known_slot_and_single_stack() -> None:
    item = ItemDefinitionData(
        item_id="rod_carbon",
        title="Carbon Rod",
        item_type="equipment",
        equipment_slot="rod",
        stack_size=1,
        max_durability=5,
        break_policy="destroy_at_zero",
        effects=[
            {
                "type": "stat_add",
                "stat": "positive_fish_reward_change_ratio",
                "value": "0.15",
            }
        ],
    )

    assert item.equipment_slot.value == "rod"
    assert item.effects[0].value == Decimal("0.15")
    with pytest.raises(ValidationError):
        ItemDefinitionData(
            item_id="invalid",
            title="Invalid",
            item_type="equipment",
            equipment_slot="backpack",
        )
    with pytest.raises(ValidationError, match="stack_size 1"):
        ItemDefinitionData(
            item_id="stacked_rod",
            title="Stacked Rod",
            item_type="equipment",
            equipment_slot="rod",
            stack_size=2,
        )


def test_unknown_or_out_of_range_effect_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ItemDefinitionData(
            item_id="unknown_effect",
            title="Unknown",
            item_type="consumable",
            effects=[{"type": "magic", "power": 10}],
        )
    with pytest.raises(ValidationError, match="robbery_protection_pct"):
        ItemDefinitionData(
            item_id="invalid_armor",
            title="Invalid Armor",
            item_type="equipment",
            equipment_slot="defense",
            effects=[
                {
                    "type": "stat_add",
                    "stat": "robbery_protection_pct",
                    "value": "1.5",
                }
            ],
        )


def test_registry_defines_caps_and_scopes_for_every_stat() -> None:
    assert set(STAT_REGISTRY) == set(StatKey)
    assert ModifierScope.ROBBERY in STAT_REGISTRY[StatKey.ROBBERY_PROTECTION_PCT].scopes
    assert STAT_REGISTRY[StatKey.NEGATIVE_FISH_REWARD_CHANGE_RATIO].maximum == Decimal("1.00")
    assert STAT_REGISTRY[StatKey.FISH_LUCK_CHANGE_RATIO].maximum == Decimal("1.00")
    assert STAT_REGISTRY[StatKey.COOLDOWN_CHANGE_RATIO].minimum == Decimal("-0.80")
    assert STAT_REGISTRY[StatKey.INVENTORY_SLOTS_ADD].value_type == "integer"


def test_integer_stats_and_multiplier_values_are_validated_by_operation() -> None:
    with pytest.raises(ValidationError, match="must be an integer"):
        ItemDefinitionData(
            item_id="fractional_storage",
            title="Fractional Storage",
            item_type="equipment",
            equipment_slot="storage",
            effects=[
                {
                    "type": "stat_add",
                    "stat": "inventory_slots_add",
                    "value": "1.5",
                }
            ],
        )

    item = ItemDefinitionData(
        item_id="scaled_armor",
        title="Scaled Armor",
        item_type="equipment",
        equipment_slot="defense",
        effects=[
            {
                "type": "stat_multiply",
                "stat": "robbery_protection_pct",
                "value": "1.5",
            }
        ],
    )
    assert item.effects[0].value == Decimal("1.5")

    with pytest.raises(ValidationError, match="must be an integer"):
        PlayerModifierSetRequest(
            stat_key="inventory_slots_add",
            operation="add",
            value="2.5",
            scope="inventory",
            source_key="invalid-slots",
            reason="Fractional inventory capacity",
        )


def test_admin_item_contract_rejects_legacy_free_form_stats() -> None:
    with pytest.raises(ValidationError, match="base_stats"):
        ItemDefinitionCreateDTO(
            item_id="legacy_rod",
            title="Legacy Rod",
            item_type="equipment",
            equipment_slot="rod",
            base_stats={"unknown_bonus": 100},
        )

    item = ItemDefinitionCreateDTO(
        item_id="modern_rod",
        title="Modern Rod",
        item_type="equipment",
        equipment_slot="rod",
        effects=[
            {
                "type": "stat_add",
                "stat": "fish_luck_change_ratio",
                "value": "0.10",
            }
        ],
    )
    assert item.effects[0].stat == StatKey.FISH_LUCK_CHANGE_RATIO
