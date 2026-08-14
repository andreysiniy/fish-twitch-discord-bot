from types import SimpleNamespace

from app.commands.casts import cast_detail_embed
from services.discord_admin_service import DiscordAdminService


def _cast(*, reward_type: str, special_result: dict, rng_trace: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        reward_type=reward_type,
        special_result=special_result,
        rng_trace=rng_trace,
    )


def test_cast_reward_details_adds_roulette_success_chance_from_trace() -> None:
    service = DiscordAdminService.__new__(DiscordAdminService)
    cast = _cast(
        reward_type="russian_roulette",
        special_result={
            "roulette": {
                "is_hit": False,
                "roll": "0.65",
                "bullets": 1,
                "chambers": 6,
            }
        },
        rng_trace=[{"stage": "roulette_hit", "threshold": "0.1666666667"}],
    )

    details = service._cast_reward_details(cast)

    assert details == {
        "roulette": {
            "is_hit": False,
            "roll": "0.65",
            "bullets": 1,
            "chambers": 6,
            "success_chance": "0.1666666667",
        }
    }


def test_cast_embed_renders_readable_robbery_details() -> None:
    item = {
        "cast_id": "cast-1",
        "status": "resolved",
        "requested_at": "2026-08-14T14:59:30+00:00",
        "username": "srakjopa",
        "location_name": "QA Robbery Lab",
        "reward": {"reward_type": "robbery", "reward_id": "robbery-1"},
        "reward_details": {
            "robbery": {
                "victim_found": True,
                "victim_name": "Smoke15",
                "is_success": True,
                "absorbed": False,
                "amount_stolen": "0.09",
                "victim_new_mass": "0",
                "chance_used": 0.95,
                "roll": "0.0657",
                "counter_actions": [],
            }
        },
        "state": {
            "mass_before": "10",
            "mass_after": "10.09",
            "mass_delta_applied": "0.09",
            "xp_before": 0,
            "xp_after": 0,
            "level_before": 1,
            "level_after": 1,
            "xp_gained": 0,
        },
        "items": [],
    }

    embed = cast_detail_embed(item)
    details = next(field.value for field in embed.fields if field.name == "Reward details")

    assert "Attacker: srakjopa" in details
    assert "Victim: Smoke15" in details
    assert "Outcome: Successful" in details
    assert "Stolen: +0.09 kg" in details
    assert "Success chance: 95.00%" in details
    assert "Robbery roll: 0.07" in details


def test_cast_embed_renders_readable_roulette_details() -> None:
    item = {
        "cast_id": "cast-2",
        "status": "resolved",
        "requested_at": "2026-08-14T14:59:30+00:00",
        "username": "srakjopa",
        "location_name": "QA Modifiers Lab",
        "reward": {"reward_type": "russian_roulette", "reward_id": "roulette-1"},
        "reward_details": {
            "roulette": {
                "is_hit": False,
                "bullets": 1,
                "chambers": 6,
                "success_chance": "0.1666666667",
                "roll": "0.651879",
                "reward": {"type": "add_mass", "mass": "5"},
                "penalty": {"type": "timeout", "duration": 120},
                "mass_delta": "5.00",
                "message": "The chamber was empty.",
            }
        },
        "state": {
            "mass_before": "10",
            "mass_after": "15",
            "mass_delta_applied": "5",
            "xp_before": 0,
            "xp_after": 0,
            "level_before": 1,
            "level_after": 1,
            "xp_gained": 0,
        },
        "items": [],
    }

    embed = cast_detail_embed(item)
    details = next(field.value for field in embed.fields if field.name == "Reward details")

    assert "Outcome: Empty chamber (safe)" in details
    assert "Loaded chambers: 1 / 6" in details
    assert "Success chance: 16.67%" in details
    assert "Applied result: Add mass +5 kg" in details
    assert "Mass change: +5 kg" in details
