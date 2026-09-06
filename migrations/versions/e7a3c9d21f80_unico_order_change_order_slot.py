"""unico parcial por slot en change_order

Revision ID: e7a3c9d21f80
Revises: b2r12adjuntos
Create Date: 2026-08-25

`upsert_change_order` es check-then-insert sin lock, sin savepoint y sin
`ON CONFLICT`, y nada lo paraba: la tabla no tenia ninguna restriccion. Entre el
SELECT y el INSERT cabe otra entrega del mismo evento —Podio reintenta, y una
app puede tener varios hooks activos— y las dos ven "no existe".

La asimetria prueba que fue un descuido y no una decision: `jobs` se blindo con
`ux_jobs_podio_item_id` y `attachments` con `ux_attachments_podio_file_id`.

`change_order`: cero duplicados en 1.285 filas (2-sep-2026). El indice entra
limpio.

POR QUE YA NO HAY INDICE PARA `"order"` — LEER ANTES DE VOLVER A PONERLO
------------------------------------------------------------------------
Esta revision creaba tambien `ux_order_job_slot` sobre
(`job_podio_id`, `tech_field`). **Se retiro el 2-sep-2026 porque el invariante
que asumia es falso**, y lo prohibiria un registro real y ya cobrado.

El caso que lo desmonta es PAR6095 (`job_podio_id` 3304340068), que durante una
semana se dio por "el unico slot duplicado en 9.801 orders":

    tech-1-ptl-original-pricing
    ORD69726  PO-PAR6095-0363  Formula 330   Units 1011 / 110 / 1107
    ORD68994  PO-PAR6095-0369  Formula 110   Unit 315 (EST60300)

No es un duplicado: son **dos POs reales del mismo subcontratista** (SUBC60341)
que juntos son los 440 que se le pagaron. Leido del item de Podio el
2-sep-2026 —`tech-1-ptl-original-pricing` resulta ser `money`, no
`calculation`, asi que ese 440 lo escribio una persona:

    job-status                Paid
    check-amount-payment-1    440.0000   <- Tech 1, PAGADO
    total-paid                  0.0000   <- "Total (Left to) Pay Tech 1"
    payment-received-1        910.0000   <- cobrado al cliente
    amount-left-to-collect      0.0000

Y cuadra al centimo por los dos lados, incluyendo la linea de ORD68994:

    builder  (90+110+130) + 110 + (90+130) = 660 = gqm-formula-total-cost
    client  (125+150+180) + 150 + (125+180) = 910 = gqm-target-sold-price
    margen  (910-660)/910 = 0.2747         = gross-profit-margin
    premium  910-660 = 250                 = gqm-pricing-return-premium-in

Borrar ORD68994 —que es lo que el indice obligaba a hacer para poder crearse—
dejaria el coste en 550 y el margen en 0.3956 sobre un job cerrado y cobrado.

Las Notes identicas en las dos filas, que fue lo que hizo pensar en un
duplicado, son un artefacto: en Podio hay UN campo de notas por slot
(`description` para tech-1, ver ORDER_PAR_FIELDS), asi que dos POs en el mismo
slot comparten texto por fuerza.

**Que haria falta antes de reponer el indice**: saber si varios POs por slot son
validos en el negocio. Si NO lo son, primero hay que reestructurar PAR6095 —PAR
tiene cuatro slots y `tech-3-formula`/`tech-4-formula` estan libres ahi— y solo
despues crear el indice. Poner el indice antes de responder esa pregunta es
prohibir por esquema algo que el negocio esta haciendo y cobrando.

Lo que si sigue en pie de aquel trabajo, y no depende del indice:

  * `POST /order` comprueba el slot contra la BD ademas de contra Podio
    (`Order.py`, `_slot_ocupado`). El guard de Podio —`is_primary_taken`— se
    saltaba cuando algo vaciaba la casilla con la fila viva, y esa es la via por
    la que entro el segundo PO de PAR6095 sin que nadie lo decidiera.
  * `upsert_order` conserva su degradacion savepoint + `IntegrityError` →
    UPDATE. Sin `ux_order_job_slot` es codigo inalcanzable, pero se deja: no
    estorba, y si el indice vuelve funciona sin tocar nada.

Ver RUNBOOK-ORDER-DUPLICADA.md para el detalle y la reconstruccion completa.

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
          WHERE c.relname = 'ux_change_order_job_slot';
         -- indisvalid debe ser TRUE. Si es FALSE:
         --   DROP INDEX CONCURRENTLY ux_change_order_job_slot;  y repetir.

POR QUE PARCIAL (`WHERE ... IS NOT NULL`)
-----------------------------------------
2 de los 1.285 change orders no tienen `podio_field` o `job_podio_id`. Un unico
total las haria colisionar ENTRE ELLAS. Mismo motivo que en
`ux_attachments_podio_file_id`.

AVISO SOBRE `alembic revision --autogenerate`
--------------------------------------------
Este indice no esta declarado en los modelos SQLModel, asi que el autogenerate
lo vera como deriva y propondra borrarlo, igual que ya hace con los cinco de
c3b8d5a1f740 / b4f7c2e18d09. **Quitar esas lineas a mano.**
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e7a3c9d21f80"
down_revision: Union[str, Sequence[str], None] = "b2r12adjuntos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDICES = (
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

    # Se comprueba ANTES de crear nada. Crear el indice con un duplicado vivo
    # es imposible, y forzarlo dejaria un indice INVALID, que no protege.
    problemas = []
    for nombre, tabla_sql, columnas, condicion in INDICES:
        filas = conexion.exec_driver_sql(SQL_DUPLICADOS.format(
            tabla=nombre, tabla_sql=tabla_sql, columnas=columnas,
            condicion=condicion)).fetchall()
        for fila in filas:
            problemas.append(f"{tabla_sql} {tuple(fila[1:-1])} x{fila[-1]}")

    if problemas:
        raise RuntimeError(
            "Hay slots duplicados; el indice unico no puede crearse. Antes de "
            "borrar nada, COMPRUEBA EN PODIO que sea de verdad un duplicado y "
            "no dos registros reales en el mismo slot: eso es exactamente lo "
            "que se dio por sentado con PAR6095 durante una semana, y era "
            "falso (ver el docstring de esta revision). "
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
