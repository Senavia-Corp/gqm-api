"""modify commissions models.

Revision ID: ebeec6ce22de
Revises: a7918ebaa3aa
Create Date: 2026-03-29 17:22:52.779910

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'ebeec6ce22de'
down_revision: Union[str, Sequence[str], None] = 'a7918ebaa3aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # 1. Crear el tipo Enum manualmente en PostgreSQL
    # Definimos el objeto Enum con el nombre exacto que espera la base de datos
    type_options = sa.Enum('Non_Comp', 'Standard',
                           'Premium', name='typeoptions')
    type_options.create(op.get_bind(), checkfirst=True)

    # --- Cambios en la tabla 'commission' ---
    op.add_column('commission', sa.Column(
        'Total_reimbursement', sa.Float(), nullable=True))
    op.add_column('commission', sa.Column(
        'Status', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('commission', sa.Column(
        'Applicable', sa.Boolean(), nullable=True))

    # Manejo de error de dedo en el nombre anterior si existe
    op.drop_column('commission', 'Total_reimbursment')

    # --- Cambios en la tabla 'commission_detail' ---
    # PASO A: Añadir la columna permitiendo NULL inicialmente para no romper filas existentes
    op.add_column('commission_detail', sa.Column(
        'Type', type_options, nullable=True))

    # PASO B: Llenar los registros actuales con un valor por defecto
    # Usamos SQL puro para asegurar que todos los detalles viejos tengan un tipo
    op.execute(
        "UPDATE commission_detail SET \"Type\" = 'Standard' WHERE \"Type\" IS NULL")

    # PASO C: Ahora que no hay nulos, aplicamos la restricción NOT NULL
    op.alter_column('commission_detail', 'Type', nullable=False)


def downgrade() -> None:
    """Downgrade schema."""

    # 1. Revertir cambios en commission_detail
    op.drop_column('commission_detail', 'Type')

    # 2. Revertir cambios en commission
    op.add_column('commission', sa.Column('Total_reimbursment', sa.DOUBLE_PRECISION(
        precision=53), autoincrement=False, nullable=True))
    op.drop_column('commission', 'Applicable')
    op.drop_column('commission', 'Status')
    op.drop_column('commission', 'Total_reimbursement')

    # 3. Eliminar el tipo Enum de PostgreSQL para dejar la DB limpia
    type_options = sa.Enum('Non_Comp', 'Standard',
                           'Premium', name='typeoptions')
    type_options.drop(op.get_bind(), checkfirst=True)
