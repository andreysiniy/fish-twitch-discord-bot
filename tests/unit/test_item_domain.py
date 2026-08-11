from decimal import Decimal

import pytest
from domain.item_schema import (
    ItemDefinitionData,
    ModifierScope,
    STAT_REGISTRY,
    StatKey,
    parse_item_definition_payload,
)
from domain.schemas.admin import ItemDefinitionCreateDTO
from domain.schemas.discord_admin import PlayerModifierSetRequest
from pydantic import ValidationError


def test_item_schema_dispatch_accepts_legacy_value_alias_and_emits_nominal_value() -> None:
    item = parse_item_definition_payload(
        {
            "item_id": "legacy_value",
            "title": "Legacy Value",
            "item_type": "material",
            "value": "12.50",
        }
    )

    assert item.nominal_value == Decimal("12.50")
    assert item.model_dump(by_alias=True)["nominal_value"] == Decimal("12.50")


def test_item_schema_dispatch_rejects_unknown_versions() -> None:
    with pytest.raises(ValueError, match="Unsupported item schema version"):
        parse_item_definition_payload(
            {
                "item_id": "future_item",
                "title": "Future Item",
                "item_type": "material",
                "schema_version": 2,
            }
        )


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


def test_duplicate_effects_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Duplicate effect is not allowed"):
        ItemDefinitionData(
            item_id="duplicate_effects",
            title="Duplicate Effects",
            item_type="equipment",
            equipment_slot="rod",
            effects=[
                {
                    "type": "stat_add",
                    "stat": "fish_luck_change_ratio",
                    "value": "0.10",
                },
                {
                    "type": "stat_add",
                    "stat": "fish_luck_change_ratio",
                    "value": "0.20",
                },
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


def test_max_charges_is_consumable_only_and_forces_single_stack() -> None:
    item = ItemDefinitionData(
        item_id="spell_potion",
        title="Spell Potion",
        item_type="consumable",
        stack_size=1,
        max_charges=5,
        effects=[
            {"type": "consume_charge", "trigger": "on_use", "amount": 1},
            {"type": "grant_mass", "mass": "5"},
        ],
    )
    assert item.max_charges == 5
    assert item.stack_size == 1

    with pytest.raises(ValidationError, match="max_charges is only allowed for consumables"):
        ItemDefinitionData(
            item_id="bad_equip_charges",
            title="Bad",
            item_type="equipment",
            equipment_slot="rod",
            max_charges=5,
        )
    with pytest.raises(ValidationError, match="max_charges is only allowed for consumables"):
        ItemDefinitionData(
            item_id="bad_material_charges",
            title="Bad",
            item_type="material",
            max_charges=5,
        )
    with pytest.raises(ValidationError, match="stack_size 1"):
        ItemDefinitionData(
            item_id="stacked_charges",
            title="Bad",
            item_type="consumable",
            stack_size=20,
            max_charges=5,
        )


def test_durability_is_equipment_only() -> None:
    with pytest.raises(ValidationError, match="max_durability is only allowed for equipment"):
        ItemDefinitionData(
            item_id="bad_consumable_durability",
            title="Bad",
            item_type="consumable",
            max_durability=150,
            break_policy="unequip_broken",
        )
    with pytest.raises(ValidationError, match="max_durability is only allowed for equipment"):
        ItemDefinitionData(
            item_id="bad_material_durability",
            title="Bad",
            item_type="material",
            max_durability=150,
            break_policy="destroy_at_zero",
        )


def test_consume_durability_is_equipment_only() -> None:
    with pytest.raises(ValidationError, match="consume_durability is only allowed for equipment"):
        ItemDefinitionData(
            item_id="bad_consumable_durability_effect",
            title="Bad",
            item_type="consumable",
            effects=[{"type": "consume_durability", "trigger": "after_cast", "amount": 1}],
        )

    item = ItemDefinitionData(
        item_id="self_consuming_rod",
        title="Self Consuming Rod",
        item_type="equipment",
        equipment_slot="rod",
        max_durability=150,
        break_policy="unequip_broken",
        effects=[{"type": "consume_durability", "trigger": "after_cast", "amount": 1}],
    )
    assert item.effects[0].type == "consume_durability"


def test_consume_charge_requires_consumable_with_max_charges() -> None:
    with pytest.raises(ValidationError, match="consume_charge is only allowed for consumables"):
        ItemDefinitionData(
            item_id="bad_equip_charge_effect",
            title="Bad",
            item_type="equipment",
            equipment_slot="rod",
            effects=[{"type": "consume_charge", "trigger": "on_use", "amount": 1}],
        )
    with pytest.raises(ValidationError, match="consume_charge requires max_charges"):
        ItemDefinitionData(
            item_id="bad_charge_without_max",
            title="Bad",
            item_type="consumable",
            effects=[{"type": "consume_charge", "trigger": "on_use", "amount": 1}],
        )


def test_item_cannot_directly_grant_itself() -> None:
    with pytest.raises(ValidationError, match="cannot grant itself"):
        ItemDefinitionData(
            item_id="self_box",
            title="Self Box",
            item_type="lootbox",
            effects=[{"type": "grant_item", "item_id": "self_box", "quantity": 2}],
        )


def test_equipment_rejects_max_charges_and_consumable_rejects_slot() -> None:
    with pytest.raises(ValidationError, match="max_charges is only allowed for consumables"):
        ItemDefinitionData(
            item_id="equip_with_charges",
            title="Bad",
            item_type="equipment",
            equipment_slot="rod",
            max_charges=3,
        )
    with pytest.raises(ValidationError, match="equipment_slot is only allowed for equipment"):
        ItemDefinitionData(
            item_id="consumable_with_slot",
            title="Bad",
            item_type="consumable",
            equipment_slot="rod",
        )



def test_compatibility_matrix_blocks_passive_stat_on_non_equipment() -> None:
    for item_type in ("consumable", "lootbox", "material", "quest", "currency", "collectible"):
        with pytest.raises(ValidationError, match="stat_add is not compatible"):
            ItemDefinitionData(
                item_id=f"bad_stat_{item_type}",
                title="Bad",
                item_type=item_type,
                effects=[
                    {
                        "type": "stat_add",
                        "stat": "fish_luck_change_ratio",
                        "value": "0.10",
                    }
                ],
            )


def test_compatibility_matrix_blocks_grant_effects_on_equipment() -> None:
    for effect in (
        {"type": "grant_item", "item_id": "rod_carbon", "quantity": 1},
        {"type": "grant_mass", "mass": "5"},
        {"type": "apply_timeout", "duration_seconds": 60},
        {"type": "loot_table_roll", "loot_table_id": "pool-1", "rolls": 1},
    ):
        with pytest.raises(ValidationError, match=f"{effect['type']} is not compatible"):
            ItemDefinitionData(
                item_id="bad_equip_grant",
                title="Bad",
                item_type="equipment",
                equipment_slot="rod",
                effects=[effect],
            )


def test_compatibility_matrix_blocks_equipment_effects_on_material() -> None:
    for effect in (
        {"type": "reroll_reward", "trigger": "after_reward_roll", "target_action_types": ["nothing"], "max_rerolls": 1},
        {"type": "block_action", "trigger": "on_robbery_attempt", "target_action_types": ["robbery"], "chance": "1"},
        {"type": "robbery_counter", "trigger": "on_robbery_attempt", "chance": "1", "action": {"type": "timeout", "duration_seconds": 30}},
        {"type": "absorb_robbery", "trigger": "on_robbery_attempt", "chance": "1"},
        {"type": "mass_floor", "protected_mass": "1000", "scopes": ["robbery"]},
    ):
        with pytest.raises(ValidationError, match=f"{effect['type']} is not compatible"):
            ItemDefinitionData(
                item_id="bad_material_effect",
                title="Bad",
                item_type="material",
                effects=[effect],
            )


def test_compatibility_matrix_accepts_valid_combinations() -> None:
    equipment = ItemDefinitionData(
        item_id="lucky_rod",
        title="Lucky Rod",
        item_type="equipment",
        equipment_slot="rod",
        effects=[
            {"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "0.10"},
            {"type": "reroll_reward", "trigger": "after_reward_roll", "target_action_types": ["nothing"], "max_rerolls": 1},
            {"type": "mass_floor", "protected_mass": "1000", "scopes": ["robbery", "negative_rewards"]},
        ],
    )
    assert equipment.effects

    consumable = ItemDefinitionData(
        item_id="gift_bag",
        title="Gift Bag",
        item_type="consumable",
        effects=[
            {"type": "grant_item", "item_id": "rod_bamboo", "quantity": 1},
            {"type": "grant_mass", "mass": "5"},
        ],
    )
    assert consumable.effects

    lootbox = ItemDefinitionData(
        item_id="lootbox_pool",
        title="Lootbox Pool",
        item_type="lootbox",
        effects=[
            {"type": "loot_table_roll", "loot_table_id": "pool-1", "rolls": 2},
        ],
    )
    assert lootbox.effects
