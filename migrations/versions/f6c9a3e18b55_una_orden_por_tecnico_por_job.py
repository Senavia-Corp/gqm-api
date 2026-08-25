"""Una orden por HUECO de técnico y job: la regla pasa a estar en la base

La regla «un subcontratista no puede tener dos órdenes en el mismo job» no
existía en la app (G6). Buscada en los tres sitios donde podría estar:

- **Sin validación en la ruta**: `POST /order/` no consultaba si ese
  subcontratista ya tenía orden en ese job.
- **Sin restricción en la base**: `OrderModel` no declaraba `unique` sobre
  `ID_Subcontractor`, `job_podio_id` ni `tech_field`, y ninguna migración creaba
  ese índice.
- Lo único parecido era una comprobación **contra Podio** (si `TECH n - Formula`
  ya tiene valor, aborta), así que **con `sync_podio=false` se podían crear N
  órdenes** para el mismo técnico.

## La clave es el HUECO, no el subcontratista

Primer intento: `(job_podio_id, ID_Subcontractor)`. **Estaba mal.** En producción
hay **29** combinaciones con dos órdenes… y las dos tienen `tech_field`
DISTINTO: el mismo subcontratista ocupa dos huecos de técnico del mismo job
(`tech-1` y `tech-2`, o `tech-2` y `tech-3`). Eso es legítimo y así está en
Podio, así que esa restricción habría rechazado datos correctos del cliente.

La regla real es **una orden por hueco**, que es justo lo que Podio impone por
estructura: `TECH n - Formula` es un campo, no una lista. Sobre esa clave
producción tiene **1** duplicado, no 29.

Índice PARCIAL: sólo aplica cuando ambas columnas tienen valor. En producción
hay 502 órdenes sin `tech_field` y 6 sin job, y no deben colisionar entre sí.

Comprobación previa fail-fast: si ya hubiera duplicados, el CONCURRENTLY
fallaría a medias y dejaría el índice INVALID.

Revision ID: f6c9a3e18b55
Revises: e5b8d2c94f77
Create Date: 2026-08-19
"""
import sqlalchemy as sa
from alembic import op

revision = 'f6c9a3e18b55'
down_revision = 'e5b8d2c94f77'
branch_labels = None
depends_on = None

NOMBRE = 'ux_order_job_tech_field'

SQL_DUPLICADOS = '''
SELECT job_podio_id, tech_field, count(*) n, array_agg("ID_Order") ids
FROM "order"
WHERE job_podio_id IS NOT NULL AND tech_field IS NOT NULL
GROUP BY 1, 2 HAVING count(*) > 1
'''


def upgrade() -> None:
    conn = op.get_bind()
    dup = conn.execute(sa.text(SQL_DUPLICADOS)).fetchall()
    if dup:
        raise RuntimeError(
            f"Hay {len(dup)} combinaciones (job, hueco de técnico) con más de una "
            f"orden — dos órdenes escribiendo en el MISMO `TECH n - Formula`. "
            f"Hay que resolverlas antes de imponer la regla. "
            f"Primeras: {[tuple(r) for r in dup[:5]]}")

    with op.get_context().autocommit_block():
        op.execute(
            f'CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {NOMBRE} '
            f'ON "order" (job_podio_id, tech_field) '
            f'WHERE job_podio_id IS NOT NULL AND tech_field IS NOT NULL')


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS {NOMBRE}')
