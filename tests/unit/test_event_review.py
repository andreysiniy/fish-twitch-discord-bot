from domain.event_review import event_review_error_message, event_review_issues


def test_event_review_issues_identifies_modifier_and_safe_limit() -> None:
    issues = event_review_issues(
        {
            "positive_fish_reward_change_percent": "500.00",
            "xp_gain_change_percent": "100",
        }
    )

    assert len(issues) == 1
    assert issues[0]["label"] == "Good Catch"
    assert issues[0]["value"] == "+500%"
    assert issues[0]["limit"] == "+/- 200%"
    assert "beyond the safe limit" in issues[0]["message"]


def test_event_review_error_has_actionable_fallback() -> None:
    message = event_review_error_message(
        {"fish_luck_change_percent": "-250", "xp_gain_change_percent": "bad"}
    )

    assert "Fish Luck is -250%" in message
    assert "XP must be a valid percentage" in message
    assert "save the event" in message
