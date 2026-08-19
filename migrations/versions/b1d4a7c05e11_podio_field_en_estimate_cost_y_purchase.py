"""podio_field en estimate_cost y purchase: el hueco de Podio deja de deducirse

Hasta ahora, qué hueco de Podio ocupaba un alquiler, un BD fee o una compra se
deducía **por posición**: el primer alquiler aprobado iba a `PURCHASE 1`, el
segundo a `PURCHASE 2`, el primer BD fee a `bldg-fees-1`. Consecuencias medidas
en la auditoría del 18-ago-2026: desaprobar un alquiler corría a todos los
siguientes, y vaciar un hueco intermedio en Podio reasignaba importes entre
registros distintos (G1 y G5).

El patrón correcto ya estaba en el repo — `ChangeOrder.podio_field` y
`Order.tech_field` — y esta migración lo extiende a las dos tablas que faltaban.

Esta revisión **sólo añade la columna**; el relleno va en la siguiente
(`b2e5c8d16f22`), a propósito: con todo a NULL el código cae al reparto
posicional de siempre, así que este paso es inerte y reversible.

AVISO PARA EL AUTOGENERATE (como en `c3b8d5a1f740` y `d95e922a318d`): a partir
de aquí son **seis** los índices que `alembic revision --autogenerate` propone
borrar por no estar declarados en los modelos —
`ix_change_order_job_podio_id`, `ix_financial_document_id_jobs`,
`ix_order_job_podio_id`, `ux_jobs_podio_item_id` y los dos únicos parciales que
crea esta migración. Hay que quitar esos `op.drop_index` a mano.

Revision ID: b1d4a7c05e11
Revises: c3b8d5a1f740
Create Date: 2026-08-18
"""
import sqlalchemy as sa
from alembic import op

revision = 'b1d4a7c05e11'
down_revision = 'c3b8d5a1f740'
branch_labels = None
depends_on = None


# El índice es PARCIAL (`WHERE podio_field IS NOT NULL`) porque durante el
# despliegue conviven filas con hueco declarado y filas sin él, y NULL no debe
# colisionar con NULL.
IDX = {
    "ux_estimate_cost_job_slot": ('estimate_cost', '"ID_Jobs", podio_field'),
    "ux_purchase_job_slot": ('purchase', '"ID_Jobs", podio_field'),
}

SQL_DUPLICADOS = """
SELECT "ID_Jobs", podio_field, count(*) n
FROM {tabla}
WHERE podio_field IS NOT NULL AND "ID_Jobs" IS NOT NULL
GROUP BY 1, 2 HAVING count(*) > 1
"""


def upgrade() -> None:
    op.add_column('estimate_cost', sa.Column('podio_field', sa.String(), nullable=True))
    op.add_column('purchase', sa.Column('podio_field', sa.String(), nullable=True))
    op.create_index('ix_estimate_cost_podio_field', 'estimate_cost', ['podio_field'])
    op.create_index('ix_purchase_podio_field', 'purchase', ['podio_field'])

    # Fail-fast antes de crear el único: si ya hubiera duplicados, el
    # CONCURRENTLY fallaría a medias y dejaría el índice INVALID.
    conn = op.get_bind()
    for nombre, (tabla, _cols) in IDX.items():
        dup = conn.execute(sa.text(SQL_DUPLICADOS.format(tabla=tabla))).fetchall()
        if dup:
            raise RuntimeError(
                f"{tabla}: hay ({len(dup)}) combinaciones (ID_Jobs, podio_field) "
                f"repetidas; el índice único no se puede crear. Primeras: {dup[:5]}")

    with op.get_context().autocommit_block():
        for nombre, (tabla, cols) in IDX.items():
            op.execute(
                f'CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {nombre} '
                f'ON {tabla} ({cols}) WHERE podio_field IS NOT NULL')


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for nombre in IDX:
            op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS {nombre}')
    op.drop_index('ix_purchase_podio_field', table_name='purchase')
    op.drop_index('ix_estimate_cost_podio_field', table_name='estimate_cost')
    op.drop_column('purchase', 'podio_field')
    op.drop_column('estimate_cost', 'podio_field')
