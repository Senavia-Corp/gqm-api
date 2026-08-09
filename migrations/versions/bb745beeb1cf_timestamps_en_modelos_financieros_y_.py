"""timestamps en modelos financieros y links de job

Revision ID: bb745beeb1cf
Revises: b4a6415aeee2
Create Date: 2026-08-09 02:46:58.568100

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bb745beeb1cf'
down_revision: Union[str, Sequence[str], None] = 'b4a6415aeee2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """REG-042/REG-101: created_at/updated_at en la capa financiera y links
    de Job (prioridad de la decisión). Backfill = now() del deploy — el
    histórico real es desconocido; la utilidad empieza hacia adelante.
    updated_at se mantiene vía onupdate del ORM (todas las escrituras pasan
    por SQLModel)."""
    op.execute('ALTER TABLE "order" ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE "order" ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE change_order ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE change_order ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE financial_document ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE financial_document ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE financial_transaction ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE financial_transaction ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE financial_doc_item ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE financial_doc_item ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE fdocument_ftransaction ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE fdocument_ftransaction ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE job_member ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE job_member ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE job_subcontractor ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE job_subcontractor ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE job_technician ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE job_technician ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE job_multiplier_range ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE job_multiplier_range ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE job_payment_unit ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()')
    op.execute('ALTER TABLE job_payment_unit ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()')


def downgrade() -> None:
    """Downgrade schema."""
    op.execute('ALTER TABLE "order" DROP COLUMN IF EXISTS updated_at')
    op.execute('ALTER TABLE "order" DROP COLUMN IF EXISTS created_at')
    op.execute('ALTER TABLE change_order DROP COLUMN IF EXISTS updated_at')
    op.execute('ALTER TABLE change_order DROP COLUMN IF EXISTS created_at')
    op.execute('ALTER TABLE financial_document DROP COLUMN IF EXISTS updated_at')
    op.execute('ALTER TABLE financial_document DROP COLUMN IF EXISTS created_at')
    op.execute('ALTER TABLE financial_transaction DROP COLUMN IF EXISTS updated_at')
    op.execute('ALTER TABLE financial_transaction DROP COLUMN IF EXISTS created_at')
    op.execute('ALTER TABLE financial_doc_item DROP COLUMN IF EXISTS updated_at')
    op.execute('ALTER TABLE financial_doc_item DROP COLUMN IF EXISTS created_at')
    op.execute('ALTER TABLE fdocument_ftransaction DROP COLUMN IF EXISTS updated_at')
    op.execute('ALTER TABLE fdocument_ftransaction DROP COLUMN IF EXISTS created_at')
    op.execute('ALTER TABLE job_member DROP COLUMN IF EXISTS updated_at')
    op.execute('ALTER TABLE job_member DROP COLUMN IF EXISTS created_at')
    op.execute('ALTER TABLE job_subcontractor DROP COLUMN IF EXISTS updated_at')
    op.execute('ALTER TABLE job_subcontractor DROP COLUMN IF EXISTS created_at')
    op.execute('ALTER TABLE job_technician DROP COLUMN IF EXISTS updated_at')
    op.execute('ALTER TABLE job_technician DROP COLUMN IF EXISTS created_at')
    op.execute('ALTER TABLE job_multiplier_range DROP COLUMN IF EXISTS updated_at')
    op.execute('ALTER TABLE job_multiplier_range DROP COLUMN IF EXISTS created_at')
    op.execute('ALTER TABLE job_payment_unit DROP COLUMN IF EXISTS updated_at')
    op.execute('ALTER TABLE job_payment_unit DROP COLUMN IF EXISTS created_at')
