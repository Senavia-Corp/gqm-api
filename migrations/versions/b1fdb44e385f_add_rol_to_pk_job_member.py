"""add_rol_to_pk_job_member

Revision ID: b1fdb44e385f
Revises: af80f381ab9c
Create Date: 2026-03-05 19:20:18.958606

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1fdb44e385f'
down_revision: Union[str, Sequence[str], None] = 'af80f381ab9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Eliminar PK actual
    op.drop_constraint('job_member_pkey', 'job_member', type_='primary')

    # 2. Hacer rol no nullable
    op.alter_column('job_member', 'rol',
                    existing_type=sa.VARCHAR(),
                    nullable=False)

    # 3. Crear nueva PK con los 3 campos
    op.create_primary_key('job_member_pkey', 'job_member', [
                          'job_id', 'member_id', 'rol'])


def downgrade() -> None:
    # Revertir todo en orden inverso
    op.drop_constraint('job_member_pkey', 'job_member', type_='primary')

    op.alter_column('job_member', 'rol',
                    existing_type=sa.VARCHAR(),
                    nullable=True)

    op.create_primary_key('job_member_pkey', 'job_member', [
                          'job_id', 'member_id'])
