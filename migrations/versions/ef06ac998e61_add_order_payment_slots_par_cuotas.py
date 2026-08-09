"""add order payment slots (PAR cuotas)

Revision ID: ef06ac998e61
Revises: 2f9e5eb00eef
Create Date: 2026-08-09 01:34:13.818479

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ef06ac998e61'
down_revision: Union[str, Sequence[str], None] = '2f9e5eb00eef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Cuotas de PAR (REG-001): Payment_1..3 en order."""
    op.add_column("order", sa.Column("Payment_1", sa.Float(), nullable=True))
    op.add_column("order", sa.Column("Payment_2", sa.Float(), nullable=True))
    op.add_column("order", sa.Column("Payment_3", sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("order", "Payment_3")
    op.drop_column("order", "Payment_2")
    op.drop_column("order", "Payment_1")
