import json
from types import SimpleNamespace

import pytest
from app.api.client import EngineClient
from app.api.errors import EngineError, localize_error
from app.api.idempotency import interaction_key
from app.bot import FisherDiscordBot
from app.config import DiscordSettings
from app.interactions.modals import (
    EventBonusModal,
    EventModal,
    FishRewardModal,
    RewardModal,
    RobberyRewardModal,
    RouletteOutcomeModal,
    RouletteSettingsModal,
    TimeoutRewardModal,
    create_reward_modal,
)
from app.interactions.reward_payloads import build_reward_payload, build_roulette_outcome
from app.interactions.sessions import WizardSessionStore
from app.presentation.embeds import event_list_entry, location_list_entry, reward_list_entry
from app.presentation.formatting import diff_lines, parse_decimal, parse_duration
from app.presentation.pagination import PagedEmbedView


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    async def setex(self, key, ttl, value):
        self.values[key] = value
        self.ttls[key] = ttl

    async def get(self, key):
        return self.values.get(key)

    async def exists(self, key):
        return key in self.values

    async def delete(self, key):
        self.values.pop(key, None)


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("90", 90), ("10m", 600), ("2h", 7200), ("1d", 86400)],
)
def test_parse_duration(value: str, seconds: int) -> None:
    assert parse_duration(value) == seconds


def test_numeric_parsing_and_diff_are_stable() -> None:
    assert parse_decimal("1.250") == "1.250"
    assert diff_lines({"a": 1}, {"a": 2}) == ["- `a`: `1` -> `2`"]
    with pytest.raises(ValueError):
        parse_decimal("NaN")


@pytest.mark.parametrize(
    ("reward_type", "parameters", "expected"),
    [
        ("fish", {"min_mass": "0.1", "max_mass": "5"}, {"min_mass": "0.1", "max_mass": "5"}),
        ("timeout", {"duration": "10m", "reason": "test"}, {"duration": 600, "reason": "test"}),
        ("robbery", {"percentage": "0.2", "range": "5"}, {"percentage": "0.2", "range": 5}),
        (
            "russian_roulette",
            {
                "bullets": "1",
                "chambers": "6",
                "reward": {"type": "add_mass", "mass": "2"},
                "penalty": {"type": "timeout", "duration": 60, "reason": "test"},
            },
            {
                "bullets": 1,
                "chambers": 6,
                "reward": {"type": "add_mass", "mass": "2"},
                "penalty": {"type": "timeout", "duration": 60, "reason": "test"},
            },
        ),
        ("nothing", {}, {}),
    ],
)
def test_build_supported_reward_payloads(reward_type, parameters, expected) -> None:
    payload = build_reward_payload(reward_type, "Test", "10", "2", "Message", parameters)
    assert payload["type"] == reward_type
    assert payload["weight"] == 10
    for key, value in expected.items():
        assert payload[key] == value


def test_reward_payloads_reject_ambiguous_fields_and_build_roulette_outcomes() -> None:
    with pytest.raises(ValueError, match="exactly one fish mass mode"):
        build_reward_payload(
            "fish",
            "Test",
            "10",
            "0",
            "",
            {"fixed_mass": "1", "percentage": "0.1"},
        )

    assert build_roulette_outcome("add_percentage_mass", "", "0.25", "", "") == {
        "type": "add_percentage_mass",
        "percentage": "0.25",
    }
    assert build_roulette_outcome("timeout", "", "", "10m", "Unlucky") == {
        "type": "timeout",
        "duration": 600,
        "reason": "Unlucky",
    }


def test_structured_modals_use_separate_fields_with_hints() -> None:
    async def save(_interaction, _payload):
        return None

    base = {"type": "fish", "weight": 1, "xp": 0, "message": "", "fixed_mass": "1"}
    reward_defaults = {
        "type": "russian_roulette",
        "bullets": 1,
        "chambers": 6,
        "reward": {"type": "add_mass", "mass": "2"},
    }
    event_payload = {
        "event_title": "Test",
        "override_loot_pool": None,
        "modifiers": {"luck_mult": "1", "xp_mult": "1", "cd_reduction": "0"},
    }
    modals = [
        RewardModal("fish", base, save),
        FishRewardModal(save, {}),
        TimeoutRewardModal(save, {}),
        RobberyRewardModal(save, {}),
        RouletteSettingsModal(save, reward_defaults),
        RouletteOutcomeModal(
            "reward",
            {**base, "type": "russian_roulette"},
            save,
            reward_defaults["reward"],
            reward_defaults,
        ),
        EventModal(save),
        EventBonusModal(event_payload, save, {}),
    ]

    assert all(len(modal.children) <= 5 for modal in modals)
    assert all(child.placeholder for modal in modals for child in modal.children)
    assert {child.label for child in modals[1].children} == {
        "Fixed mass",
        "Minimum mass",
        "Maximum mass",
        "Percentage",
    }
    assert {child.label for child in modals[6].children} == {
        "Name",
        "Override location",
        "Luck multiplier",
        "XP multiplier",
        "Cooldown reduction",
    }

    first_step_labels = {
        reward_type: {child.label for child in create_reward_modal(reward_type, save).children}
        for reward_type in ("fish", "timeout", "robbery", "russian_roulette")
    }
    assert first_step_labels == {
        "fish": {"Fixed mass", "Minimum mass", "Maximum mass", "Percentage"},
        "timeout": {"Duration", "Reason"},
        "robbery": {"Fixed mass", "Percentage", "Victim search range"},
        "russian_roulette": {"Bullets", "Chambers", "Safe message", "Shot message"},
    }


def test_entity_list_entries_include_all_parameters_without_truncation() -> None:
    marker = "complete-message-marker"
    reward = {
        "reward_id": "reward-1",
        "type": "russian_roulette",
        "name": "Risky reward",
        "weight": 100,
        "probability": 0.5,
        "xp": 25,
        "message": "M" * 300,
        "bullets": 1,
        "chambers": 6,
        "safe_message": "S" * 300,
        "shot_message": "X" * 300 + marker,
        "reward": {"type": "add_mass", "mass": "2.5"},
        "penalty": {"type": "timeout", "duration": 60, "reason": "Unlucky"},
    }
    title, details = reward_list_entry(reward)
    view = PagedEmbedView(1, "Rewards", [reward], reward_list_entry, page_size=1)
    rendered = "\n".join(field.value for field in view.embed().fields)

    assert title == "Risky reward"
    assert "probability: 50.00%" in details
    assert all(f"{key}:" in details for key in reward)
    assert marker in rendered

    location = {
        "location_id": "river",
        "location_name": "River",
        "items_drop_rate": 0.1,
        "requirements": {"level": 2},
        "reward_count": 4,
        "version": 3,
    }
    event = {
        "id": 7,
        "event_title": "Double XP",
        "is_active": True,
        "override_loot_pool": "river",
        "modifiers": {"xp_mult": "2", "bonus_mass": "0.15"},
        "version": 2,
        "updated_at": "2026-08-02T00:00:00+00:00",
    }
    assert all(f"{key}:" in location_list_entry(location)[1] for key in location)
    assert all(f"{key}:" in event_list_entry(event)[1] for key in event)


def test_error_mapping_includes_request_id() -> None:
    message = localize_error(
        EngineError(409, "CONFIG_VERSION_CONFLICT", "conflict", request_id="request-42")
    )
    assert "Another administrator" in message
    assert "request-42" in message
    assert interaction_key(123, "reward.create") == "discord:123:reward.create"


@pytest.mark.asyncio
async def test_wizard_sessions_are_scoped_and_refresh_ttl() -> None:
    redis = FakeRedis()
    store = WizardSessionStore(redis, ttl_seconds=900)
    flow_id = await store.create(123, {"version": 1})
    key = f"fish:discord:session:123:{flow_id}"

    assert json.loads(redis.values[key]) == {"version": 1}
    assert redis.ttls[key] == 900
    assert await store.get(999, flow_id) is None

    await store.update(123, flow_id, {"version": 2})
    assert await store.get(123, flow_id) == {"version": 2}
    await store.delete(123, flow_id)
    assert await store.get(123, flow_id) is None


def test_command_tree_and_optional_empty_environment(monkeypatch) -> None:
    monkeypatch.setenv("DEV_GUILD_ID", "")
    gateway_settings = DiscordSettings(_env_file=None)
    bot = FisherDiscordBot(gateway_settings)
    fish = bot.tree.get_command("fish")

    assert fish is not None
    assert {command.name for command in fish.commands} == {
        "account",
        "config",
        "event",
        "help",
        "link",
        "location",
        "placeholders",
        "reward",
        "setup",
        "status",
        "unlink",
    }
    assert gateway_settings.DEV_GUILD_ID is None
    assert bot.intents.guilds is True
    assert bot.intents.message_content is False


@pytest.mark.parametrize(
    "permissions",
    [
        SimpleNamespace(manage_guild=True, administrator=False),
        SimpleNamespace(manage_guild=False, administrator=True),
    ],
)
def test_engine_headers_use_authoritative_interaction_permissions(permissions) -> None:
    interaction = SimpleNamespace(
        guild_id=996458228911198218,
        channel_id=996458228911198219,
        permissions=permissions,
        user=SimpleNamespace(
            id=474223161790169104,
            guild_permissions=SimpleNamespace(manage_guild=False, administrator=False),
        ),
    )
    client = EngineClient(DiscordSettings(_env_file=None))

    headers = client._headers(interaction, "request-id", None)

    assert headers["X-Discord-Manage-Guild"] == "true"
