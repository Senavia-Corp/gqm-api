"""indexes for job_podio_id and financial_document ID_Jobs

Revision ID: 373a3e43a266
Revises: ef06ac998e61
Create Date: 2026-08-09 01:56:25.204976

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '373a3e43a266'
down_revision: Union[str, Sequence[str], None] = 'ef06ac998e61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Índices para los hot paths (revisión DB del Bloque 1).

    order.job_podio_id y change_order.job_podio_id se filtran en cada
    recalculate_and_apply (PATCH /jobs) y en cada webhook; financial_document
    "ID_Jobs" es FK sin índice. CONCURRENTLY para no bloquear escrituras al
    aplicar en producción (main, ~miles de filas).
    """
    with op.get_context().autocommit_block():
        op.execute('CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_order_job_podio_id ON "order" (job_podio_id)')
        op.execute('CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_change_order_job_podio_id ON change_order (job_podio_id)')
        op.execute('CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_financial_document_id_jobs ON financial_document ("ID_Jobs")')


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_order_job_podio_id")
    op.execute("DROP INDEX IF EXISTS ix_change_order_job_podio_id")
    op.execute("DROP INDEX IF EXISTS ix_financial_document_id_jobs")
