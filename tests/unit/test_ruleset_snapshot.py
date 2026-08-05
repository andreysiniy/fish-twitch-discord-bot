from decimal import Decimal
from types import SimpleNamespace

from domain.schemas.fishing import FishingResult
from services.fishing import ruleset_snapshot
from services.fishing import trace_builder


def _user(**overrides):
    values = {
        "channel_id": 7,
        "user_twitch_id": "viewer-1",
        "username": "viewer_one",
        "current_location_id": "abyss",
        "current_mass": Decimal("1000.00"),
        "xp": 100,
        "equipped_items": [],
        "channel": SimpleNamespace(
            id=7, config={"custom_params": {"cooldown": 30}}
        ),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _EqItem:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _InvItem:
    def __init__(self, id, current_durability, definition):
        self.id = id
        self.current_durability = current_durability
        self.definition = definition


def test_snapshot_hash_is_stable_across_key_order() -> None:
    a = {"b": 1, "a": 2, "list": [{"z": 1, "y": 2}]}
    b = {"a": 2, "b": 1, "list": [{"y": 2, "z": 1}]}
    assert ruleset_snapshot.hash_payload(a) == ruleset_snapshot.hash_payload(b)


def test_snapshot_hash_changes_with_content() -> None:
    a = ruleset_snapshot.hash_payload({"reward": "fish", "weight": "10"})
    b = ruleset_snapshot.hash_payload({"reward": "fish", "weight": "11"})
    assert a != b


def test_build_ruleset_snapshot_payload_keeps_deterministic_fields() -> None:
    rewards = [
        {
            "type": "fish",
            "weight": 100,
            "percentage": "0.20",
            "message": "You caught {percentage}",
            "se_token": "SECRET",  # must be dropped
        }
    ]
    items = [
        {
            "db_id": 9,
            "item_id": "leviathan_rod",
            "weight": 500,
            "rarity": "legendary",
            "definition_version": 3,
            "description": "should not be part of snapshot",
        }
    ]
    payload = ruleset_snapshot.build_ruleset_snapshot_payload(
        user=_user(),
        pool=SimpleNamespace(location_name="Abyss", id=5, version=2),
        rewards=rewards,
        item_entries=items,
        items_drop_rate=0.06,
        channel_config_version=4,
        modifier_schema_version=2,
        engine_version="test-build",
        event_snapshot={"id": 17, "title": "Lucky", "version": 3},
        effective_params_snapshot={"cooldown": "30"},
    )
    assert payload["location"]["location_name"] == "Abyss"
    assert payload["reward_entries"][0]["type"] == "fish"
    assert "se_token" not in payload["reward_entries"][0]
    assert "description" not in payload["item_entries"][0]
    assert payload["item_entries"][0]["item_id"] == "leviathan_rod"
    assert payload["event"]["id"] == 17


def test_equipped_items_snapshot_captures_durability() -> None:
    definition = _EqItem(item_id="storm_rod", title="Storm Rod")
    inv = _InvItem(id=90, current_durability=5, definition=definition)
    record = SimpleNamespace(slot="rod", inventory_item=inv)
    user = _user(equipped_items=[record])
    snapshot = trace_builder.build_equipped_items_snapshot(user)
    assert snapshot[0]["slot"] == "rod"
    assert snapshot[0]["current_durability"] == 5
    assert snapshot[0]["item_id"] == "storm_rod"


def test_result_snapshot_converts_decimals() -> None:
    result = FishingResult(
        loot={"type": "fish", "percentage": "0.20"},
        item_drop=None,
        username="viewer_one",
        xp_gained=10,
        mass_gained=Decimal("20.00"),
        is_level_up=False,
        old_level=1,
        new_level=1,
        luck_used=1.4,
    )
    snap = trace_builder.build_result_snapshot(result)
    assert snap["mass_gained"] == "20.00"
    assert snap["loot"]["percentage"] == "0.20"


def test_rng_trace_includes_reward_stage() -> None:
    result = FishingResult(
        loot={"type": "fish"},
        item_drop=None,
        username="viewer_one",
        xp_gained=0,
        mass_gained=Decimal("0"),
        is_level_up=False,
        old_level=1,
        new_level=1,
        luck_used=1.0,
        reward_roll_trace={
            "roll": "742.180000",
            "total_weight": "1000",
            "selected_id": "reward-fish-20pct",
            "selected_probability": "0.08",
        },
    )
    trace = trace_builder.build_rng_trace(result)
    assert trace[0]["stage"] == "ordinary_reward"
    assert trace[0]["selected_reward_id"] == "reward-fish-20pct"
