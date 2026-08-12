"""Raise the default economy mass limit to the provider points range."""

from alembic import op
import sqlalchemy as sa


revision = "20260812_0037"
down_revision = "20260812_0036"
branch_labels = None
depends_on = None

DEFAULT_MAX_TRANSACTION_MASS = "2147483647"
LEGACY_DEFAULT_MAX_TRANSACTION_MASS = "1000"


def upgrade() -> None:
    op.alter_column(
        "channel_economy_settings",
        "max_transaction_mass",
        existing_type=sa.Numeric(18, 2),
        server_default=sa.text(DEFAULT_MAX_TRANSACTION_MASS),
    )
    # The previous migration assigned 1000 kg to every new row.  Only rows
    # still carrying that exact legacy default are upgraded; an owner-set
    # custom limit remains untouched.
    op.execute(
        sa.text(
            "UPDATE channel_economy_settings "
            "SET max_transaction_mass = :new_default "
            "WHERE max_transaction_mass = :legacy_default"
        ).bindparams(
            new_default=DEFAULT_MAX_TRANSACTION_MASS,
            legacy_default=LEGACY_DEFAULT_MAX_TRANSACTION_MASS,
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE channel_economy_settings "
            "SET max_transaction_mass = :legacy_default "
            "WHERE max_transaction_mass = :new_default"
        ).bindparams(
            new_default=DEFAULT_MAX_TRANSACTION_MASS,
            legacy_default=LEGACY_DEFAULT_MAX_TRANSACTION_MASS,
        )
    )
    op.alter_column(
        "channel_economy_settings",
        "max_transaction_mass",
        existing_type=sa.Numeric(18, 2),
        server_default=sa.text(LEGACY_DEFAULT_MAX_TRANSACTION_MASS),
    )
