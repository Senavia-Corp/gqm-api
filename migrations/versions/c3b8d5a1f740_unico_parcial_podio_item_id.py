"""indice UNICO parcial en jobs.podio_item_id

Revision ID: c3b8d5a1f740
Revises: a7c1f3e94b20
Create Date: 2026-08-10 21:12:00.000000

`podio_item_id` es único **de facto** (0 duplicados en producción hoy) pero nada
lo garantiza: el índice actual es `unique=False` y no hay constraint. Un import
que empareje mal, o dos entregas de webhook concurrentes que ganen la carrera
las dos, dejan dos jobs apuntando al mismo item de Podio y la paridad deja de
ser demostrable — el conteo cuadra y los datos no.

Parcial (`WHERE podio_item_id IS NOT NULL`) porque los jobs locales creados con
`sync_podio=false` no tienen item y son varios: un único total los haría
colisionar entre ellos.

CONCURRENTLY y `autocommit_block`, como `373a3e43a266`: la tabla de producción
tiene 7.541 filas y no se puede bloquear para escritura durante el cutover.

ORDEN DE EJECUCIÓN — importa. En el cutover esta migración va **después** de la
purga de huérfanas y del borrado de los jobs locales, no antes. Si se ejecuta
demasiado pronto y hay duplicados, la comprobación de abajo la para en seco con
la lista, en vez de dejar un índice inválido que Postgres marca y nadie mira.

AVISO PARA EL PRÓXIMO AUTOGENERATE — este índice se suma a la lista de falsos
positivos. `alembic revision --autogenerate` propone ahora borrar **CUATRO**
índices, no los tres de siempre:

    op.drop_index('ix_change_order_job_podio_id', ...)
    op.drop_index('ix_financial_document_id_jobs', ...)
    op.drop_index('ix_order_job_podio_id', ...)
    op.drop_index('ux_jobs_podio_item_id', ...)      <- este

Los cuatro existen en la BD y ninguno está declarado en los modelos SQLModel,
así que autogenerate los ve como deriva. **Quitar esas líneas a mano.** Aceptar
la propuesta borra el único índice que garantiza que dos jobs no apunten al
mismo item de Podio.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c3b8d5a1f740'
down_revision: Union[str, Sequence[str], None] = 'a7c1f3e94b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOMBRE = "ux_jobs_podio_item_id"

SQL_DUPLICADOS = """
SELECT podio_item_id, count(*) AS n, string_agg("ID_Jobs", ', ' ORDER BY "ID_Jobs")
  FROM jobs
 WHERE podio_item_id IS NOT NULL
 GROUP BY podio_item_id
HAVING count(*) > 1
 ORDER BY n DESC
 LIMIT 20
"""


def upgrade() -> None:
    conexion = op.get_bind()
    duplicados = conexion.exec_driver_sql(SQL_DUPLICADOS).fetchall()
    if duplicados:
        detalle = "; ".join(
            f"item {item} en {jobs} ({n} jobs)" for item, n, jobs in duplicados)
        raise RuntimeError(
            f"Hay {len(duplicados)} podio_item_id duplicados; el índice único no "
            f"puede crearse todavía. Esta migración va DESPUÉS de la purga de "
            f"huérfanas. Duplicados: {detalle}"
        )

    with op.get_context().autocommit_block():
        op.execute(
            f'CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {NOMBRE} '
            f'ON jobs (podio_item_id) WHERE podio_item_id IS NOT NULL')


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {NOMBRE}")
