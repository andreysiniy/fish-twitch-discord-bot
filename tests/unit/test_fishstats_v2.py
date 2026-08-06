
from core.messages import DEFAULT_MESSAGES, PLACEHOLDER_DESCRIPTIONS, MsgKey, resolve_message
from decimal import Decimal

from domain.schemas.fishing import PlayerStatsDTO


def test_fishstats_default_template_no_longer_uses_resist() -> None:
    template = DEFAULT_MESSAGES[MsgKey.PROFILE_STATS_DETAILED]
    assert "Resist" not in template
    # Bonus stats are whole segments carried by placeholder values, so a
    # zero-value stat can be dropped from the line entirely.
    for placeholder in (
        "{luck_fmt}",
        "{good_catch_fmt}",
        "{bad_catch_fmt}",
        "{xp_fmt}",
        "{cd_fmt}",
        "{item_drop_fmt}",
        "{item_rarity_fmt}",
    ):
        assert placeholder in template


def test_fishstats_default_template_resolves_v2_concepts() -> None:
    message = resolve_message(
        {},
        MsgKey.PROFILE_STATS_DETAILED,
        username="viewer",
        level=4,
        xp=790,
        xp_next=800,
        rod_name="No rod",
        luck_fmt="🍀 Fish Luck: +40% | ",
        good_catch_fmt="🐟 Good Catch: +5% | ",
        bad_catch_fmt="🛟 Bad Catch: -5% | ",
        cd_fmt="⏱ CD: -50% | ",
        xp_fmt="✨ XP: +100% | ",
        item_drop_fmt="",
        item_rarity_fmt="",
        current_mass="339.94kg",
        total_fish_stat=20,
        rank=1,
        total_mass="1000",
    )
    assert "Fish Luck: +40%" in message
    assert "Good Catch: +5%" in message
    assert "Bad Catch: -5%" in message
    assert "CD: -50%" in message
    assert "Item Drop" not in message
    assert "Resist" not in message


def test_bonus_segment_omits_zero_stats() -> None:
    from services.fishing_service import _bonus_segment

    assert _bonus_segment("🍀", "Fish Luck", 0) == ""
    assert _bonus_segment("🍀", "Fish Luck", Decimal("0")) == ""
    assert _bonus_segment("🐟", "Good Catch", Decimal("5")) == "🐟 Good Catch: +5% | "
    assert _bonus_segment("⏱", "CD", Decimal("-50")) == "⏱ CD: -50% | "


def test_resist_only_means_robbery_in_placeholder_catalog() -> None:
    desc = PLACEHOLDER_DESCRIPTIONS.get("resist_fmt", "")
    assert "robbery" in desc.lower() or "resistance" in desc.lower()


def test_player_stats_dto_carries_v2_bonuses() -> None:
    dto = PlayerStatsDTO(
        rod_name="No rod",
        positive_fish_reward_change_percent=Decimal("5"),
        cooldown_change_percent=Decimal("-50"),
    )
    assert dto.positive_fish_reward_change_percent == Decimal("5")
    assert dto.cooldown_change_percent == Decimal("-50")
