import pytest
from core.messages import DEFAULT_MESSAGES, MsgKey, message_placeholder_catalog
from domain.config_schema import GameConfig, RewardDefinition
from pydantic import TypeAdapter, ValidationError

reward_adapter = TypeAdapter(RewardDefinition)


def test_game_config_rejects_inverted_robbery_chances() -> None:
    with pytest.raises(ValidationError):
        GameConfig(rob_min_chance="0.9", rob_max_chance="0.1")


def test_fish_reward_requires_exactly_one_mass_mode() -> None:
    with pytest.raises(ValidationError):
        reward_adapter.validate_python(
            {
                "type": "fish",
                "weight": 10,
                "fixed_mass": "1.0",
                "min_mass": "0.5",
                "max_mass": "2.0",
            }
        )


def test_reward_rejects_unknown_fields_and_assigns_stable_id() -> None:
    reward = reward_adapter.validate_python(
        {"type": "timeout", "weight": 1, "duration": 60, "reason": "test"}
    )
    assert reward.reward_id
    with pytest.raises(ValidationError):
        reward_adapter.validate_python({"type": "nothing", "weight": 1, "unknown": True})


def test_roulette_rejects_more_bullets_than_chambers() -> None:
    with pytest.raises(ValidationError):
        reward_adapter.validate_python(
            {"type": "russian_roulette", "weight": 1, "bullets": 5, "chambers": 4}
        )


def test_message_placeholder_catalog_matches_default_templates() -> None:
    catalog = {item["message_key"]: item["placeholders"] for item in message_placeholder_catalog()}

    assert set(catalog) == {key.value for key in MsgKey}
    assert {item["name"] for item in catalog["robbery_success"]} == {
        "attacker",
        "attacker_gain",
        "attacker_mass",
        "victim",
        "victim_loss",
        "victim_mass",
    }
    assert "{attacker_mass}" in DEFAULT_MESSAGES[MsgKey.ROBBERY_SUCCESS]
