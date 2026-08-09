"""qbo failed events dead letter

Revision ID: 8ac457c78452
Revises: bb745beeb1cf
Create Date: 2026-08-09 09:46:10.514174

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8ac457c78452'
down_revision: Union[str, Sequence[str], None] = 'bb745beeb1cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """REG-057/REG-118: dead-letter de eventos del webhook QBO."""
    op.create_table(
        "qbo_failed_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("realm_id", sa.String(), nullable=True),
        sa.Column("entity_name", sa.String(), nullable=True),
        sa.Column("entity_id", sa.String(), nullable=True),
        sa.Column("operation", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_qbo_failed_events_entity_name", "qbo_failed_events", ["entity_name"])
    op.create_index("ix_qbo_failed_events_entity_id", "qbo_failed_events", ["entity_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("qbo_failed_events")
