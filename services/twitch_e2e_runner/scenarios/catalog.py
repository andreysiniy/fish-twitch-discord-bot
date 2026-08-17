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

