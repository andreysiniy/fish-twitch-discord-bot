import json

import pytest
from app.api.errors import EngineError, localize_error
from app.api.idempotency import interaction_key
from app.interactions.reward_payloads import build_reward_payload
from app.interactions.sessions import WizardSessionStore
from app.presentation.formatting import diff_lines, parse_decimal, parse_duration


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
        ("fish", "range=0.1,5", {"min_mass": "0.1", "max_mass": "5"}),
        ("timeout", "duration=10m;reason=test", {"duration": 600, "reason": "test"}),
        ("robbery", "percentage=0.2;range=5", {"percentage": "0.2", "range": 5}),
        ("russian_roulette", "bullets=1;chambers=6", {"bullets": 1, "chambers": 6}),
        ("nothing", "", {}),
    ],
)
def test_build_supported_reward_payloads(reward_type, parameters, expected) -> None:
    payload = build_reward_payload(reward_type, "Test", "10", "2", "Message", parameters)
    assert payload["type"] == reward_type
    assert payload["weight"] == 10
    assert expected.items() <= payload.items()


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
