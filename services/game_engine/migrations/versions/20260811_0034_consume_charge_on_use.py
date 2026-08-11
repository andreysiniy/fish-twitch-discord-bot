"""Make charge consumption explicit at the item-use boundary.

Charge-based consumables are consumed by ``use_item``.  Older definitions
stored cast/drop triggers even though no runtime pipeline executed those
triggers, so normalize them to the only supported trigger without changing
the amount or any other effect payload.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "20260811_0034"
down_revision = "20260811_0033"
branch_labels = None
depends_on = None


def _normalize(effects) -> list:
    if effects is None:
        return []
    if isinstance(effects, str):
        effects = json.loads(effects)
    if not isinstance(effects, list):
        return effects
    return [
        {**effect, "trigger": "on_use"}
        if isinstance(effect, dict)
        and effect.get("type") == "consume_charge"
        and effect.get("trigger") != "on_use"
        else effect
        for effect in effects
    ]


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, effects FROM item_definitions WHERE jsonb_typeof(effects) = 'array'")
    ).fetchall()
    for item_id, effects in rows:
        normalized = _normalize(effects)
        if normalized != effects:
            bind.execute(
                sa.text(
                    "UPDATE item_definitions SET effects = CAST(:effects AS jsonb) "
                    "WHERE id = :id"
                ),
                {"effects": json.dumps(normalized), "id": item_id},
            )


def downgrade() -> None:
    # ``on_use`` is the only semantically correct trigger.  There is no safe
    # inverse because the old cast/drop values were non-functional.
    return None
