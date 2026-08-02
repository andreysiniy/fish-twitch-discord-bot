from decimal import Decimal

from domain.logic.formulas import calculate_typed_robbery


def test_typed_robbery_splits_attack_evasion_protection_and_protected_mass() -> None:
    chance, stealable, stolen = calculate_typed_robbery(
        base_chance=Decimal("0.60"),
        attacker_chance_add=Decimal("0.15"),
        victim_evasion=Decimal("0.20"),
        victim_mass=Decimal("1000"),
        protected_mass=Decimal("250"),
        base_amount=Decimal("300"),
        attacker_amount_bonus=Decimal("0.50"),
        victim_protection=Decimal("0.40"),
    )

    assert chance == Decimal("0.55")
    assert stealable == Decimal("750")
    assert stolen == Decimal("270.00")


def test_typed_robbery_never_crosses_protected_floor() -> None:
    _, stealable, stolen = calculate_typed_robbery(
        base_chance=Decimal("1"),
        attacker_chance_add=Decimal("0"),
        victim_evasion=Decimal("0"),
        victim_mass=Decimal("100"),
        protected_mass=Decimal("90"),
        base_amount=Decimal("1000"),
        attacker_amount_bonus=Decimal("10"),
        victim_protection=Decimal("0"),
    )
    assert stealable == Decimal("10")
    assert stolen == Decimal("10.00")
