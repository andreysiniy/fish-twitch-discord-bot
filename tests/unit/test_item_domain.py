from decimal import Decimal

import pytest
from domain.item_schema import (
    ItemDefinitionData,
    ModifierScope,
    STAT_REGISTRY,
    StatKey,
)
from domain.schemas.admin import ItemDefinitionCreateDTO
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
                "stat": "positive_mass_bonus_pct",
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
    assert STAT_REGISTRY[StatKey.NEGATIVE_MASS_REDUCTION_PCT].maximum == Decimal("0.95")


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
                "stat": "loot_luck_pct",
                "value": "0.10",
            }
        ],
    )
    assert item.effects[0].stat == StatKey.LOOT_LUCK_PCT
