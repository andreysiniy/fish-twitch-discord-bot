import asyncio

import discord
from app.interactions.effect_builder import (
    describe_effect,
    effect_to_choice,
    parse_decimal_safe,
    serialize_draft,
)


def test_serialize_stat_add_effect() -> None:
    effect = serialize_draft({"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "0.10"})
    assert effect["trigger"] == "passive"
    assert effect["value"] == "0.10"


def test_serialize_stat_multiply_preserves_trigger() -> None:
    effect = serialize_draft({"type": "stat_multiply", "stat": "xp_gain_change_ratio", "value": "2"})
    assert effect["type"] == "stat_multiply"
    assert effect["value"] == "2"


def test_describe_passive_effect_shows_percent() -> None:
    text = describe_effect({"type": "stat_add", "stat": "positive_fish_reward_change_ratio", "value": "0.05"})
    assert "Positive Fish Reward" in text or "positive_fish_reward_change_ratio" in text
    assert "5%" in text


def test_describe_grant_effect() -> None:
    text = describe_effect({"type": "grant_item", "item_id": "storm_rod", "quantity": 2})
    assert "storm_rod" in text
    assert "2" in text


def test_effect_to_choice_returns_type() -> None:
    assert effect_to_choice({"type": "grant_mass"}) == "grant_mass"


def test_parse_decimal_safe_handles_bad_values() -> None:
    assert parse_decimal_safe("0.5") is not None
    assert parse_decimal_safe("not-a-number") == 0


def test_serialize_draft_leaves_non_passive_untouched() -> None:
    effect = serialize_draft({"type": "grant_mass", "mass": "5.5"})
    assert effect["type"] == "grant_mass"
    assert effect["mass"] == "5.5"


def test_every_selectable_effect_has_a_typed_modal() -> None:
    """UI audit §5.2: no effect type may silently fall back to raw JSON."""
    from app.interactions.effect_builder import EFFECT_SELECT_OPTIONS, modal_for_effect

    for option in EFFECT_SELECT_OPTIONS:
        modal = modal_for_effect(option.value, lambda payload: None)
        assert modal is not None, f"{option.value} has no typed modal"
        assert isinstance(modal, discord.ui.Modal)


def test_reroll_reward_modal_builds_target_list() -> None:
    from app.interactions.effect_builder import RerollRewardModal

    saved = []

    async def fake_submit(interaction):
        modal = RerollRewardModal(saved.append)
        modal.targets._value = "nothing, negative_mass"
        modal.max_rerolls._value = "2"
        modal.durability_cost._value = "1"
        await modal.on_submit(interaction)

    class FakeInteraction:
        class response:
            @staticmethod
            async def send_message(*args, **kwargs):
                return None

    asyncio.run(fake_submit(FakeInteraction))
    assert saved[0]["type"] == "reroll_reward"
    assert saved[0]["target_action_types"] == ["nothing", "negative_mass"]
    assert saved[0]["max_rerolls"] == 2
    assert saved[0]["durability_cost"] == 1
