from services.legacy_rewards import convert_legacy_rewards


def test_legacy_rewards_convert_old_types_and_placeholders() -> None:
    result = convert_legacy_rewards(
        {
            "base_cooldown": 300,
            "rewards": {
                "points": [
                    {"weight": 10, "value": -250, "message": "Lost {value}."}
                ],
                "percentage_points": [
                    {"weight": 20, "percentage": -0.3, "message": "Lost {percentage}."}
                ],
                "misc": {"title": "Jigsaw", "weight": 5, "message": "Hello {username}."},
                "nothing": [{"weight": 6, "message": "Nothing."}],
                "dupe": {
                    "id": "dupe_3",
                    "locked": True,
                    "weight": 7,
                    "amount": 3,
                    "delay": 2,
                    "message": "{username} fishes {amount} times.",
                },
                "robbery": [
                    {
                        "weight": 8,
                        "value": 200,
                        "range": 5,
                        "message": "Robbery time.",
                        "robbery_message": "{victim} lost {value} to {username}.",
                    }
                ],
                "russian_roulette": [
                    {
                        "weight": 9,
                        "bullets": 1,
                        "chambers": 6,
                        "penalty_type": "percentage",
                        "percentage": 0.2,
                        "shot_message": "Lost {percentage}.",
                        "safe_message": "Safe.",
                    }
                ],
            },
        }
    )

    assert result.source_counts["misc"] == 1
    assert result.target_counts == {
        "dupe": 1,
        "fish": 2,
        "nothing": 2,
        "robbery": 1,
        "russian_roulette": 1,
    }
    assert result.rewards[0]["fixed_mass"] == "-0.25"
    assert result.rewards[0]["message"] == "Lost {amount}."
    assert result.rewards[1]["percentage"] == "-0.3"
    assert result.rewards[2]["type"] == "nothing"
    assert result.rewards[2]["name"] == "Jigsaw"
    assert result.rewards[4]["type"] == "dupe"
    assert result.rewards[4]["amount"] == 3
    assert result.rewards[5]["mass"] == "0.2"
    assert result.rewards[5]["success_message"] == (
        "{victim} lost {attacker_gain} to {attacker}."
    )
    assert result.rewards[6]["penalty"] == {
        "type": "add_percentage_mass",
        "percentage": "-0.2",
    }
    assert any("locked" in warning for warning in result.warnings)
    assert any("base_cooldown" in warning for warning in result.warnings)


def test_legacy_roulette_point_penalty_converts_to_negative_mass() -> None:
    result = convert_legacy_rewards(
        {
            "russian_roulette": {
                "weight": 1,
                "penalty_type": "points",
                "value": 150,
                "shot_message": "Lost {value}.",
            }
        }
    )

    assert result.rewards[0]["penalty"] == {"type": "add_mass", "mass": "-0.15"}
    assert result.rewards[0]["shot_message"] == "Lost {amount}."
