"""add jobs.podio_app_year

Revision ID: 2f9e5eb00eef
Revises: a16928946379
Create Date: 2026-08-09 01:21:58.632557

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f9e5eb00eef'
down_revision: Union[str, Sequence[str], None] = 'a16928946379'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Añade jobs.podio_app_year (año de la app Podio del item, REG-015).

    Backfill: donde hay Date_assigned se toma su año como mejor aproximación
    histórica; los NULL restantes los resuelve el próximo webhook/sync.
    """
    op.add_column("jobs", sa.Column("podio_app_year", sa.Integer(), nullable=True))
    op.execute(
        'UPDATE jobs SET podio_app_year = EXTRACT(YEAR FROM "Date_assigned")::int '
        'WHERE "Date_assigned" IS NOT NULL'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("jobs", "podio_app_year")
