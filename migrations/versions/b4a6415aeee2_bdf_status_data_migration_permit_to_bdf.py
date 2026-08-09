"""bdf status data migration (permit to bdf)

Revision ID: b4a6415aeee2
Revises: dae64aec87f2
Create Date: 2026-08-09 02:45:40.335726

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4a6415aeee2'
down_revision: Union[str, Sequence[str], None] = 'dae64aec87f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """REG-041: migrate_bdf_status.py como revisión Alembic (idempotente).

    1. EstimateCost Permit → Cost_type='BDF', Status='Estimated'.
    2. BDF sin Status → Status='Approved' (y Client_price desde Builder_cost
       si estaba vacío).
    En develop es no-op (0 filas); en prod (main) normaliza el modelo BDF.
    Los agregados de los jobs afectados los recalcula el próximo
    recalculate_and_apply (PATCH/webhook); no se fuerzan aquí para mantener
    la migración puramente SQL.
    """
    bind = op.get_bind()
    bind.execute(sa.text("""
        UPDATE estimate_cost
        SET "Cost_type" = 'BDF', "Status" = 'Estimated'
        WHERE "Cost_type" = 'Permit'
    """))
    bind.execute(sa.text("""
        UPDATE estimate_cost
        SET "Status" = 'Approved',
            "Client_price" = COALESCE("Client_price", "Builder_cost")
        WHERE "Cost_type" = 'BDF'
          AND ("Status" IS NULL OR "Status" = '')
    """))


def downgrade() -> None:
    """Data-fix: sin downgrade (Permit ya no existe como tipo)."""
    pass
