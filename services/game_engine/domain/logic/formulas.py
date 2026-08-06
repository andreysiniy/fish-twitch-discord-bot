from decimal import ROUND_HALF_UP, Decimal

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


def calculate_xp_gain(base_xp: int, item_xp: int, bonus_pct: float) -> int:
    return int((base_xp + item_xp) * (1 + bonus_pct))


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


def calculate_robbery_chance(
    base_chance: float,
    attacker_luck: float,
    victim_resistance: float,
    resist_divisor: float = 100.0,
    min_chance: float = 0.05,
    max_chance: float = 0.95,
) -> float:
    mitigation = 1 / (1 + (victim_resistance / resist_divisor))
    final_chance = base_chance * attacker_luck * mitigation
    return max(min(max_chance, final_chance), min_chance)


def calculate_robbery_loss(
    potential_loss: Decimal,
    victim_resistance: float | Decimal,
    loss_divisor: float | Decimal = Decimal("50"),
) -> Decimal:
    resistance = to_decimal(victim_resistance)
    divisor = to_decimal(loss_divisor)
    loss_modifier = Decimal("1") / (Decimal("1") + (resistance / divisor))
    return quantize_mass(to_decimal(potential_loss) * loss_modifier)


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
