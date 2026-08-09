"""backfill amount_applied proporcional y recomputo de balances

Revision ID: dae64aec87f2
Revises: 373a3e43a266
Create Date: 2026-08-09 02:44:22.133672

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dae64aec87f2'
down_revision: Union[str, Sequence[str], None] = '373a3e43a266'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """REG-043: backfill de amount_applied (pagos por lote) + recómputo.

    Decisión confirmada: los links NULL de una transacción se reparten
    PROPORCIONALMENTE al Total_Amount de cada documento sobre el remanente
    (total del cheque − montos ya conocidos). Después se recomputan
    Balance_Amount/Percentage_Paid de TODOS los docs desde SUM(amount_applied)
    (excluyendo transacciones anuladas) — la única fórmula válida (capa 2).
    En prod (main) esto corrige los 457 links NULL / 92 balances negativos.
    """
    bind = op.get_bind()

    txs = bind.execute(sa.text("""
        SELECT ft."ID_FTransaction" AS tid, COALESCE(ft."Total_Amount", 0) AS ttotal
        FROM financial_transaction ft
        WHERE EXISTS (
            SELECT 1 FROM fdocument_ftransaction l
            WHERE l.ftransaction_id = ft."ID_FTransaction"
              AND l.amount_applied IS NULL)
    """)).mappings().all()

    for tx in txs:
        links = bind.execute(sa.text("""
            SELECT l.fdocument_id AS did, l.amount_applied AS applied,
                   COALESCE(fd."Total_Amount", 0) AS dtotal
            FROM fdocument_ftransaction l
            JOIN financial_document fd ON fd."ID_FinancialDoc" = l.fdocument_id
            WHERE l.ftransaction_id = :tid
        """), {"tid": tx["tid"]}).mappings().all()

        known = sum(float(l["applied"]) for l in links if l["applied"] is not None)
        null_links = [l for l in links if l["applied"] is None]
        if not null_links:
            continue
        remaining = max(float(tx["ttotal"]) - known, 0.0)
        weight_total = sum(float(l["dtotal"]) for l in null_links)

        for l in null_links:
            if weight_total > 0:
                share = round(remaining * float(l["dtotal"]) / weight_total, 2)
            else:
                share = round(remaining / len(null_links), 2)
            bind.execute(sa.text("""
                UPDATE fdocument_ftransaction SET amount_applied = :a
                WHERE ftransaction_id = :tid AND fdocument_id = :did
            """), {"a": share, "tid": tx["tid"], "did": l["did"]})

    # Recómputo global desde los links (excluyendo transacciones anuladas)
    bind.execute(sa.text("""
        UPDATE financial_document fd SET
          "Balance_Amount" = COALESCE(fd."Total_Amount", 0) - COALESCE(p.paid, 0),
          "Percentage_Paid" = CASE WHEN COALESCE(fd."Total_Amount", 0) > 0
              THEN ROUND((COALESCE(p.paid, 0) / fd."Total_Amount" * 100)::numeric, 2)
              ELSE 0 END
        FROM (
            SELECT l.fdocument_id, SUM(COALESCE(l.amount_applied, 0)) AS paid
            FROM fdocument_ftransaction l
            JOIN financial_transaction ft ON ft."ID_FTransaction" = l.ftransaction_id
            WHERE COALESCE(ft.is_voided, FALSE) = FALSE
            GROUP BY l.fdocument_id
        ) p
        WHERE p.fdocument_id = fd."ID_FinancialDoc"
    """))


def downgrade() -> None:
    """Data-fix: sin downgrade (los valores previos eran NULL/incorrectos)."""
    pass
