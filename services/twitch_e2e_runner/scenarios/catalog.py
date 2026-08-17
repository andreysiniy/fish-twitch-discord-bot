"""Complete catalog from the race-testing specification.

Entries without a deterministic fixture are intentionally reported as skipped
until their corresponding backend hook is enabled, never as false passes.
"""

ECONOMY_SCENARIOS = tuple(f"R{i:02d}" for i in range(1, 93))
GAMEPLAY_SCENARIOS = tuple(f"R{i:02d}" for i in range(93, 118))
HEALTH_SCENARIOS = tuple(f"H{i:02d}" for i in range(1, 13))
CHANNEL_SCENARIOS = tuple(f"C{i:02d}" for i in range(1, 13))
BOUNDARY_SCENARIOS = tuple(f"E{i:02d}" for i in range(1, 11))
SOAK_SCENARIOS = tuple(f"S{i:02d}" for i in range(1, 6))

# Dispatch groups mirror the specification sections. Keeping these sets
# explicit prevents a gameplay race from accidentally being sent through the
# economy runner merely because both use an ``Rxx`` identifier.
ECONOMY_RACES = {
    f"R{i:02d}" for i in list(range(1, 38)) + list(range(49, 93))
}
INVENTORY_RACES = {"R42", "R43", "R44", "R99", "R104", "R105", "R106", "R107", "R108"}
CROSS_DOMAIN_RACES = {
    "R38", "R39", "R40", "R41", "R45", "R46", "R47", "R48",
    "R111", "R112", "R113", "R114", "R115", "R116", "R117",
}
FISHING_RACES = set(GAMEPLAY_SCENARIOS) - INVENTORY_RACES
WORKER_RACES = {f"R{i:02d}" for i in list(range(28, 32)) + list(range(82, 89))}
RESILIENCE_RACES = {
    f"R{i:02d}" for i in list(range(32, 38)) + list(range(53, 68)) + list(range(77, 82))
}
PROVIDER_FAULT_RACES = {
    f"R{i:02d}" for i in list(range(9, 17)) + list(range(68, 76))
}
ALL_SCENARIOS = (
    "smoke",
    "permissions",
    *ECONOMY_SCENARIOS,
    *GAMEPLAY_SCENARIOS,
    *HEALTH_SCENARIOS,
    *CHANNEL_SCENARIOS,
    *BOUNDARY_SCENARIOS,
    *SOAK_SCENARIOS,
)

