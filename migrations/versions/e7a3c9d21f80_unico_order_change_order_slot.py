"""unico parcial por slot en order y change_order

Revision ID: e7a3c9d21f80
Revises: b2r12adjuntos
Create Date: 2026-08-25

Nada impedia que dos Orders ocuparan el mismo slot: la tabla no tenia ninguna
restriccion. La asimetria prueba que fue un descuido y no una decision: `jobs`
se blindo con `ux_jobs_podio_item_id` y `attachments` con
`ux_attachments_podio_file_id`.

Hay DOS caminos que meten una segunda fila en un slot, y este docstring solo
documentaba el primero hasta el 2-sep-2026:

  1. `upsert_order` / `upsert_change_order` son check-then-insert sin lock, sin
     savepoint y sin `ON CONFLICT`. Entre el SELECT y el INSERT cabe otra
     entrega del mismo evento —Podio reintenta, y una app puede tener varios
     hooks activos— y las dos ven "no existe". Bug real; #130 lo degrada a
     UPDATE en cuanto exista el indice.

  2. `POST /order` comprobaba el slot con `is_primary_taken`
     (`order_changeorder_mappers.py:160`), que mira la CASILLA DE PODIO y no la
     BD. Si algo vacia la casilla mientras la fila sigue viva, el guard da el
     slot por libre. **Este es el camino por el que entro el duplicado que hay
     hoy**, no el 1.

EL DANO ESTA VIVO. Re-medido en produccion el 2-sep-2026:

    job_podio_id 3304340068 -> PAR6095 (PAR, 2026)
    tech_field   tech-1-ptl-original-pricing
    ORD68994 = 110   ORD69726 = 330      <- unico slot duplicado en 9.801 orders

`recalculate_job_fields` recorre TODAS las orders del job y acumula
`Adj_formula`, asi que hoy suma 660 donde deberia sumar 550.

`change_order`: cero duplicados en 1.285 filas.

COMO SE CREO, SEGUN `tlactivity` DE PAR6095
--------------------------------------------
    2026-08-18 18:56:18   MEM60012   Order deleted   PO-PAR6095-0363
    2026-08-18 19:03:10   MEM60012   Order created   PO-PAR6095-0363 -> ORD69726

Siete minutos, una persona, la misma PO: no es una carrera. El DELETE pre-#129
emitia `[]` sin mirar si quedaba otra Order en el slot, vacio la casilla de
Podio con ORD68994 todavia dentro, y el CREATE de siete minutos despues la vio
libre. Ver RUNBOOK-ORDER-DUPLICADA.md.

Cuidado al datar filas de esta tabla: 9.599 de las 9.801 orders comparten el
`created_at` `2026-08-11T03:20:03.808Z` — un backfill masivo. Ese campo no dice
cuando se creo el dato de negocio.

POR QUE PARCIAL (`WHERE ... IS NOT NULL`)
-----------------------------------------
503 de las 9.801 orders no tienen `tech_field` o `job_podio_id`, y 2 de los
1.285 change orders no tienen `podio_field` o `job_podio_id`. Un unico total las
haria colisionar ENTRE ELLAS. Mismo motivo que en `ux_attachments_podio_file_id`.

COMO SE APLICA — las mismas dos trampas de b4f7c2e18d09
-------------------------------------------------------
  1. **Cadena de conexion DIRECTA, no la del pooler.** Los
     `CREATE INDEX CONCURRENTLY` FALLAN a traves de PgBouncer.

  2. **Verificar `indisvalid` DESPUES.** Si el CONCURRENTLY se corta a medias,
     Postgres deja el indice marcado INVALID; y como la sentencia lleva
     `IF NOT EXISTS`, un segundo intento lo da por bueno sin arreglarlo. Un
     indice INVALID no impide duplicados: seria creerse protegido sin estarlo,
     que es peor que no tenerlo.

         SELECT c.relname, i.indisvalid
           FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
          WHERE c.relname IN ('ux_order_job_slot', 'ux_change_order_job_slot');
         -- indisvalid debe ser TRUE en los dos. Si alguno es FALSE:
         --   DROP INDEX CONCURRENTLY <nombre>;  y repetir.

ESTA MIGRACION VA A ABORTAR HASTA QUE SE CONSOLIDE ORD68994/ORD69726
--------------------------------------------------------------------
Y es deliberado: crear el indice con el duplicado vivo es imposible, y hacerlo
"a la fuerza" dejaria un indice INVALID. La consolidacion es una decision
humana con dinero de por medio — ver RUNBOOK-ORDER-DUPLICADA.md.

Antes de consolidar hay que tener DESPLEGADO el arreglo de los mappers de
PATCH/DELETE (PR #129): sin el, borrar una de las dos filas emite `[]` a Podio y
se lleva por delante el importe de la que sobrevive. **Ya lo esta**: verificado
el 2-sep-2026, produccion sirve `f0db2d8` (tip de `main`) y `cfd9360` (#129) y
`a524086` (#130) son ancestros suyos.

AVISO SOBRE `alembic revision --autogenerate`
--------------------------------------------
Ninguno de estos indices esta declarado en los modelos SQLModel, asi que el
autogenerate los vera como deriva y propondra borrarlos, igual que ya hace con
los cinco de c3b8d5a1f740 / b4f7c2e18d09. **Quitar esas lineas a mano.**
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e7a3c9d21f80"
down_revision: Union[str, Sequence[str], None] = "b2r12adjuntos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDICES = (
    ("ux_order_job_slot", '"order"', "job_podio_id, tech_field",
     "tech_field IS NOT NULL AND job_podio_id IS NOT NULL"),
    ("ux_change_order_job_slot", "change_order", "job_podio_id, podio_field",
     "podio_field IS NOT NULL AND job_podio_id IS NOT NULL"),
)

SQL_DUPLICADOS = """
SELECT '{tabla}' AS tabla, {columnas}, count(*) AS n
  FROM {tabla_sql}
 WHERE {condicion}
 GROUP BY {columnas}
HAVING count(*) > 1
 LIMIT 20
"""


def upgrade() -> None:
    conexion = op.get_bind()

    # Los DOS se comprueban ANTES de crear ninguno: abortar a medias dejaria
    # una tabla protegida y la otra no, que es peor de diagnosticar.
    problemas = []
    for nombre, tabla_sql, columnas, condicion in INDICES:
        filas = conexion.exec_driver_sql(SQL_DUPLICADOS.format(
            tabla=nombre, tabla_sql=tabla_sql, columnas=columnas,
            condicion=condicion)).fetchall()
        for fila in filas:
            problemas.append(f"{tabla_sql} {tuple(fila[1:-1])} x{fila[-1]}")

    if problemas:
        raise RuntimeError(
            "Hay slots duplicados; los indices unicos no pueden crearse. Cada "
            "duplicado es dinero que se esta sumando dos veces en "
            "`recalculate_job_fields`: hay que consolidarlos A MANO antes "
            "(RUNBOOK-ORDER-DUPLICADA.md), con el PR #129 ya desplegado. "
            f"Duplicados: {'; '.join(problemas)}"
        )

    with op.get_context().autocommit_block():
        for nombre, tabla_sql, columnas, condicion in INDICES:
            op.execute(
                f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {nombre} "
                f"ON {tabla_sql} ({columnas}) WHERE {condicion}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for nombre, _, _, _ in INDICES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {nombre}")
