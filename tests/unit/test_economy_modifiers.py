from domain.item_schema import ModifierScope, StatKey


def test_external_economy_has_no_player_modifier_stat_keys() -> None:
    assert not hasattr(StatKey, "SELL_RATE_BONUS_PCT")
    assert not hasattr(StatKey, "BUY_DISCOUNT_PCT")
    assert not hasattr(StatKey, "POINTS_FLAT_BONUS")
    assert not hasattr(ModifierScope, "ECONOMY")
