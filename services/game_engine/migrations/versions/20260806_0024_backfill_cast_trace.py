"""Backfill fishing-cast reward trace from JSONB snapshots.

Older ledger rows (recorded before the reward trace columns existed) keep the
full selection trace in the rng_trace JSONB array and the selected reward in
reward_snapshot, but the dedicated numeric columns stayed NULL, so cast detail
views showed empty probability/roll fields.

This migration copies the recoverable values into the columns:

- reward_id / reward_weight  <- reward_snapshot (selected reward)
- reward_total_weight /
  reward_probability / reward_roll <- ordinary_reward trace stage
- item_drop_probability / item_drop_roll / item_drop_succeeded
                                <- item_drop_gate trace stage

The update is idempotent (only rows whose reward_probability is NULL) and
non-destructive: no existing value is overwritten and nothing is deleted.

Revision ID: 20260806_0024
Revises: 20260802_0023
"""

from alembic import op
from sqlalchemy import text

revision = "20260806_0024"
down_revision = "20260802_0023"
branch_labels = None
depends_on = None


def _ordinary_reward(field: str) -> str:
    return (
        "(SELECT elem->>'%s' FROM jsonb_array_elements(rng_trace) elem "
        "WHERE elem->>'stage' = 'ordinary_reward' LIMIT 1)" % field
    )


def _item_drop_gate(field: str) -> str:
    return (
        "(SELECT elem->>'%s' FROM jsonb_array_elements(rng_trace) elem "
        "WHERE elem->>'stage' = 'item_drop_gate' LIMIT 1)" % field
    )


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text("""UPDATE fishing_casts SET
             reward_id = COALESCE(reward_id, reward_snapshot->>'reward_id'),
             reward_weight = COALESCE(
                 reward_weight, (reward_snapshot->>'weight')::numeric
             ),
             reward_total_weight = COALESCE(
                 reward_total_weight,
                 %(total_weight)s::numeric
             ),
             reward_probability = COALESCE(
                 reward_probability,
                 %(probability)s::numeric
             ),
             reward_roll = COALESCE(
                 reward_roll, %(roll)s::numeric
             ),
             item_drop_probability = COALESCE(
                 item_drop_probability,
                 %(drop_probability)s::numeric
             ),
             item_drop_roll = COALESCE(
                 item_drop_roll, %(drop_roll)s::numeric
             ),
             item_drop_succeeded = CASE
                 WHEN %(drop_success)s IS NOT NULL
                 THEN %(drop_success)s::boolean
                 ELSE item_drop_succeeded
             END
           WHERE reward_probability IS NULL
             AND jsonb_typeof(rng_trace) = 'array'"""
        % {
            "total_weight": _ordinary_reward("total_weight"),
            "probability": _ordinary_reward("selected_probability"),
            "roll": _ordinary_reward("roll"),
            "drop_probability": _item_drop_gate("threshold"),
            "drop_roll": _item_drop_gate("roll"),
            "drop_success": _item_drop_gate("success"),
        })
    )


def downgrade() -> None:
    # Backfilled trace columns are derived data; downgrade restores the
    # pre-migration state by clearing only values that came from JSONB.
    conn = op.get_bind()
    conn.execute(
        text("""UPDATE fishing_casts SET
             reward_id = NULL,
             reward_weight = NULL,
             reward_total_weight = NULL,
             reward_probability = NULL,
             reward_roll = NULL,
             item_drop_probability = NULL,
             item_drop_roll = NULL,
             item_drop_succeeded = FALSE
           WHERE jsonb_typeof(rng_trace) = 'array'
             AND reward_snapshot ? 'weight'""")
    )
