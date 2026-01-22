"""MODIFY Columnas de Phone y Email a array.

Revision ID: 2a317a04c9c1
Revises: eb2f970986a0
Create Date: 2026-01-22 13:39:01.211084

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2a317a04c9c1'
down_revision: Union[str, Sequence[str], None] = 'eb2f970986a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('client', 'Email_Address')
    op.drop_column('client', 'Phone_Number')

    op.add_column(
        'client',
        sa.Column('Email_Address', sa.JSON(), nullable=True)
    )
    op.add_column(
        'client',
        sa.Column('Phone_Number', sa.JSON(), nullable=True)
    )

    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_column('client', 'Email_Address')
    op.drop_column('client', 'Phone_Number')

    op.add_column(
        'client',
        sa.Column('Email_Address', sa.VARCHAR(), nullable=True)
    )
    op.add_column(
        'client',
        sa.Column('Phone_Number', sa.VARCHAR(), nullable=True)
    )

    # ### end Alembic commands ###
