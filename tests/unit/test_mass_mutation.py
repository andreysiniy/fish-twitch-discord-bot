from decimal import Decimal
from types import SimpleNamespace

from domain.logic.mass import apply_mass_mutation


def test_mass_mutation_clamps_negative_delta_and_tracks_only_applied_positive_mass() -> None:
    holder = SimpleNamespace(
        current_mass=Decimal("1.00"),
        total_mass_stat=Decimal("10.00"),
    )

    applied = apply_mass_mutation(holder, Decimal("-2.25"), track_total=True)

    assert applied == Decimal("-1.00")
    assert holder.current_mass == Decimal("0.00")
    assert holder.total_mass_stat == Decimal("10.00")


def test_mass_mutation_tracks_positive_grants_once() -> None:
    holder = SimpleNamespace(
        current_mass=Decimal("1.00"),
        total_mass_stat=Decimal("10.00"),
    )

    applied = apply_mass_mutation(holder, Decimal("2.345"), track_total=True)

    assert applied == Decimal("2.35")
    assert holder.current_mass == Decimal("3.35")
    assert holder.total_mass_stat == Decimal("12.35")


def test_mass_mutation_supports_explicit_floor_without_changing_total_mass() -> None:
    holder = SimpleNamespace(
        current_mass=Decimal("4.00"),
        total_mass_stat=Decimal("10.00"),
    )

    applied = apply_mass_mutation(
        holder,
        Decimal(-10),
        mass_floor=Decimal("2.50"),
        track_total=False,
    )

    assert applied == Decimal("-1.50")
    assert holder.current_mass == Decimal("2.50")
    assert holder.total_mass_stat == Decimal("10.00")
