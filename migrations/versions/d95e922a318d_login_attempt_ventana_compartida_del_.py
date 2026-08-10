"""login_attempt: ventana compartida del rate limit

Revision ID: d95e922a318d
Revises: c60a71121b93
Create Date: 2026-08-10 13:51:07.954788

Crea la tabla que sostiene el rate limit de login entre instancias serverless.
El limitador era un dict en memoria del proceso y en Vercel no frenaba nada
(12 logins fallidos seguidos contra gqm-api-dev: 12x 401, ni un 429).

⚠️ OJO, revisada a mano: el autogenerate de Alembic quería añadir tambien

    op.drop_index('ix_change_order_job_podio_id',  table_name='change_order')
    op.drop_index('ix_financial_document_id_jobs', table_name='financial_document')
    op.drop_index('ix_order_job_podio_id',         table_name='order')

porque esos indices no estan declarados en los modelos SQLModel — los crea a
proposito la migracion 373a3e43a266 con CREATE INDEX CONCURRENTLY. Borrarlos
habria tirado a la basura esa optimizacion en produccion sin que nadie lo
pidiera. Se han quitado de esta migracion. Si un futuro autogenerate los vuelve
a proponer, es el mismo falso positivo: NO aceptarlo.
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd95e922a318d'
down_revision: Union[str, Sequence[str], None] = 'c60a71121b93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'login_attempt',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('attempt_key', sqlmodel.sql.sqltypes.AutoString(length=320), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_login_attempt_attempt_key'), 'login_attempt', ['attempt_key'], unique=False)
    op.create_index(op.f('ix_login_attempt_created_at'), 'login_attempt', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_login_attempt_created_at'), table_name='login_attempt')
    op.drop_index(op.f('ix_login_attempt_attempt_key'), table_name='login_attempt')
    op.drop_table('login_attempt')
