from decimal import Decimal

import pytest
from domain.config_schema import EventModifiers, EventModifiersV2
from pydantic import ValidationError


def test_v2_neutral_values_map_to_zero_ratios() -> None:
    modifiers = EventModifiersV2()
    payload = modifiers.to_resolver_payload()
    for value in payload.values():
        assert value == Decimal("0")


def test_v2_spec_example_maps_human_percent_to_ratio() -> None:
    modifiers = EventModifiersV2(
        fish_luck_change_percent=Decimal("40"),
        positive_fish_reward_change_percent=Decimal("5"),
        negative_fish_reward_change_percent=Decimal("-5"),
        xp_gain_change_percent=Decimal("100"),
        cooldown_change_percent=Decimal("-50"),
    )
    payload = modifiers.to_resolver_payload()
    assert payload["fish_luck_change_ratio"] == Decimal("0.40")
    assert payload["positive_fish_reward_change_ratio"] == Decimal("0.05")
    assert payload["negative_fish_reward_change_ratio"] == Decimal("-0.05")
    assert payload["xp_gain_change_ratio"] == Decimal("1.00")
    assert payload["cooldown_change_ratio"] == Decimal("-0.50")


def test_v2_schema_version_is_pinned_to_two() -> None:
    with pytest.raises(ValidationError):
        EventModifiersV2(schema_version=3)


def test_legacy_event_modifiers_reject_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        EventModifiers(luck_mult=Decimal("1"), unknown_key=1)  # type: ignore[call-arg]


def test_v2_reject_out_of_bounds_cooldown() -> None:
    with pytest.raises(ValidationError):
        EventModifiersV2(cooldown_change_percent=Decimal("101"))


def _event(modifiers: dict):
    from types import SimpleNamespace

    return SimpleNamespace(id=17, event_title="Lucky", modifiers=modifiers)


def test_v2_event_contributions_feed_the_resolver() -> None:
    from domain.item_schema import ModifierScope
    from services.player_modifier_service import PlayerModifierService

    event = _event(
        EventModifiersV2(
            fish_luck_change_percent=Decimal("40"),
            positive_fish_reward_change_percent=Decimal("5"),
            xp_gain_change_percent=Decimal("100"),
            cooldown_change_percent=Decimal("-50"),
        ).model_dump(mode="json")
    )
    contributions = PlayerModifierService._event_contributions(event, ModifierScope.FISHING)

    values = {
        str(c.stat.value): c.value
        for c in contributions
    }
    assert values["fish_luck_change_ratio"] == Decimal("0.40")
    assert values["positive_fish_reward_change_ratio"] == Decimal("0.05")
    assert values["xp_gain_change_ratio"] == Decimal("1.00")
    assert values["cooldown_change_ratio"] == Decimal("-0.50")
    assert all(c.scope == ModifierScope.FISHING for c in contributions)


def test_legacy_event_contributions_still_resolve() -> None:
    from domain.item_schema import ModifierScope
    from services.player_modifier_service import PlayerModifierService

    event = _event({"luck_mult": "1.4", "xp_mult": "2", "cd_reduction": "0.5", "bonus_mass": "5"})
    contributions = PlayerModifierService._event_contributions(event, ModifierScope.FISHING)
    values = {str(c.stat.value): c.value for c in contributions}
    assert values["fish_luck_change_ratio"] == Decimal("0.40")
    assert values["positive_fish_reward_change_ratio"] == Decimal("5")
    assert values["xp_gain_change_ratio"] == Decimal("1")


def test_event_create_request_accepts_v2_human_percents() -> None:
    from domain.schemas.discord_admin import DiscordEventCreateRequest

    request = DiscordEventCreateRequest(
        event_title="Lucky",
        modifiers={
            "schema_version": 2,
            "fish_luck_change_percent": "40",
            "positive_fish_reward_change_percent": "5",
            "xp_gain_change_percent": "100",
            "cooldown_change_percent": "-50",
        },
    )
    assert isinstance(request.modifiers, EventModifiersV2)
    assert request.modifiers.fish_luck_change_percent == Decimal("40")


def test_event_create_request_still_accepts_legacy_modifiers() -> None:
    from domain.schemas.discord_admin import DiscordEventCreateRequest

    request = DiscordEventCreateRequest(
        event_title="Lucky",
        modifiers={"luck_mult": "1.4", "bonus_mass": "5"},
    )
    assert isinstance(request.modifiers, EventModifiers)
    assert request.modifiers.bonus_mass == Decimal("5")


def test_event_patch_request_passes_none_modifiers_through() -> None:
    from domain.schemas.discord_admin import DiscordEventPatchRequest

    request = DiscordEventPatchRequest(expected_version=1, event_title="New name")
    assert request.modifiers is None
