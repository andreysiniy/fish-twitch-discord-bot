"""Add CHECK constraints for string state/role/type fields.

Revision ID: 20260802_0016
Revises: 20260802_0015
"""

from alembic import op
from sqlalchemy import inspect

revision = "20260802_0016"
down_revision = "20260802_0015"
branch_labels = None
depends_on = None

CONSTRAINTS = {
    "item_definitions": [
        (
            "ck_item_definitions_type_slot",
            "(type = 'equipment' AND slot IS NOT NULL AND stack_size = 1) "
            "OR (type <> 'equipment' AND slot IS NULL)",
        ),
        (
            "ck_item_definitions_durability_policy",
            "(break_policy = 'indestructible' AND max_durability IS NULL) "
            "OR (break_policy <> 'indestructible' AND max_durability IS NOT NULL)",
        ),
    ],
    "economy_operations": [
        (
            "ck_economy_operations_operation_type",
            "operation_type IN ('sell','buy','reward_points')",
        ),
        (
            "ck_economy_operations_state",
            "state IN ('pending','queued','processing','external_pending','external_applied',"
            "'completed','compensated','failed','reconciliation_required','dead_letter')",
        ),
    ],
    "outbox_events": [
        (
            "ck_outbox_events_state",
            "state IN ('pending','processing','processed','failed',"
            "'dead_letter','compensated','reconciliation_required')",
        ),
    ],
    "channel_access_roles": [
        (
            "ck_channel_access_roles_role",
            "role IN ('owner','editor','moderator')",
        ),
    ],
    "admin_audit_log": [
        (
            "ck_admin_audit_log_result",
            "result IN ('success','error')",
        ),
    ],
}


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    for table, constraints in CONSTRAINTS.items():
        existing = {check["name"] for check in inspector.get_check_constraints(table)}
        for name, sql in constraints:
            if name in existing:
                continue
            # Defensive normalization before a strict CHECK can be introduced:
            # equipment must carry an explicit slot (legacy rows may not have one).
            if name == "ck_item_definitions_type_slot":
                op.execute(
                    "UPDATE item_definitions SET slot = 'rod' "
                    "WHERE type = 'equipment' AND slot IS NULL"
                )
            op.create_check_constraint(name, table, sql)


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    for table, constraints in CONSTRAINTS.items():
        existing = {check["name"] for check in inspector.get_check_constraints(table)}
        for name, _sql in constraints:
            if name in existing:
                op.drop_constraint(name, table, type_="check")
