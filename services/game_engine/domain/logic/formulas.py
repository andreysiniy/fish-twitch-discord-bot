from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from domain.logic.mass import ZERO_MASS, quantize_mass, to_decimal


def calculate_xp_required(level: int, base: int = 100, exponent: float = 1.5) -> int:
    return int(base * (level**exponent))


def is_level_up(
    current_xp: int,
    current_level: int,
    base: int = 100,
    exponent: float = 1.5,
) -> bool:
    return current_xp >= calculate_xp_required(current_level, base, exponent)


def calculate_xp_gain(base_xp: int, item_xp: int, bonus_pct: Decimal) -> int:
    return int((Decimal(base_xp) + Decimal(item_xp)) * (Decimal("1") + bonus_pct))


def apply_fish_reward_modifiers(
    raw_delta: Decimal,
    fish_luck_change_ratio: Decimal,
    positive_fish_reward_change_ratio: Decimal,
    negative_fish_reward_change_ratio: Decimal,
    mass_floor: Decimal = ZERO_MASS,
    user_balance: Decimal = ZERO_MASS,
    round_places: int = 2,
) -> Decimal:
    """Pure modifiers v2 formula for a fish reward (spec sections 7.2-7.4).

    Positive delta:  raw × max(0.01, 1 + luck) × max(0, 1 + positive)
    Negative delta:  raw ÷ max(0.01, 1 + luck) × max(0, 1 + negative)

    Rounds exactly once at the end (``round_places`` decimals). A
    ``mass_floor`` protects negative rewards from dropping the balance below
    the floor.
    """
    luck_factor = max(Decimal("0.01"), Decimal("1") + to_decimal(fish_luck_change_ratio))
    quantum = Decimal("1").scaleb(-round_places)
    if to_decimal(raw_delta) >= ZERO_MASS:
        positive_factor = max(
            Decimal("0"), Decimal("1") + to_decimal(positive_fish_reward_change_ratio)
        )
        return (to_decimal(raw_delta) * luck_factor * positive_factor).quantize(
            quantum, rounding=ROUND_HALF_UP
        )
    negative_factor = max(
        Decimal("0"), Decimal("1") + to_decimal(negative_fish_reward_change_ratio)
    )
    delta = to_decimal(raw_delta) / luck_factor * negative_factor
    if to_decimal(mass_floor) > ZERO_MASS:
        delta = max(delta, to_decimal(mass_floor) - to_decimal(user_balance))
    return delta.quantize(quantum, rounding=ROUND_HALF_UP)


def calculate_typed_robbery(
    *,
    base_chance: Decimal,
    attacker_chance_add: Decimal,
    victim_evasion: Decimal,
    victim_mass: Decimal,
    protected_mass: Decimal,
    base_amount: Decimal,
    attacker_amount_bonus: Decimal,
    victim_protection: Decimal,
    min_chance: Decimal = Decimal("0"),
    max_chance: Decimal = Decimal("1"),
) -> tuple[Decimal, Decimal, Decimal]:
    chance = min(
        max(base_chance + attacker_chance_add - victim_evasion, min_chance),
        max_chance,
    )
    stealable = max(victim_mass - protected_mass, ZERO_MASS)
    stolen = base_amount * (Decimal("1") + attacker_amount_bonus)
    stolen *= Decimal("1") - victim_protection
    stolen = quantize_mass(min(max(stolen, ZERO_MASS), stealable))
    return chance, stealable, stolen


def geometric_first_success_stats(probability: Decimal) -> tuple[Decimal, int, int]:
    """Expected casts, p50 and p90 for a geometric first-success process.

    Each cast succeeds independently with per-cast probability ``probability``:

    - expected casts to first success = 1 / p;
    - p50 = ceil(ln(2) / -ln(1 - p));
    - p90 = ceil(ln(10) / -ln(1 - p)).

    Raises ``ValueError`` when ``probability`` is not within (0, 1).
    """
    p = to_decimal(probability)
    if p <= Decimal("0") or p >= Decimal("1"):
        raise ValueError("probability must be in (0, 1)")
    log_fail = (Decimal("1") - p).ln()
    expected = (Decimal("1") / p).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    p50 = int((-Decimal("2").ln() / log_fail).to_integral_value(rounding=ROUND_CEILING))
    p90 = int((-Decimal("10").ln() / log_fail).to_integral_value(rounding=ROUND_CEILING))
    return expected, p50, p90
