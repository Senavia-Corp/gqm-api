"""Relleno de podio_field: congela la posición actual como hueco declarado

Segunda mitad de `b1d4a7c05e11`. Aquella añadió la columna; ésta la rellena
deduciendo el hueco por la posición **actual**, que hoy es la verdad de facto:
el reparto que hace `qid_mapper` es alquileres aprobados primero y compras
después, cada grupo ordenado por su clave primaria.

## Escala

Contra producción (18-ago-2026): 7.591 jobs, pero sólo **1 alquiler aprobado,
2 BD fees aprobados y 11 compras con job**. Son decenas de filas, no miles: esta
migración no necesita ventana de mantenimiento ni troceado.

## Idempotente y reanudable

El `row_number()` se calcula sobre TODAS las filas del job (asignadas o no),
pero el `UPDATE` sólo toca las que siguen a NULL. Volver a correrla no mueve lo
ya asignado y completa lo que falte.

## El riesgo, y por qué se acota

Esto da por cierto que *orden en la base == orden en Podio*. Nada lo garantiza.
Antes de correrla en producción hay que pasar `scripts/verificar_slots_podio.py`
en modo informe: compara importe por importe contra Podio. Y si algo se
congelase mal, el `downgrade` devuelve todo a NULL, que es el estado en el que
el código cae al reparto posicional de siempre.

Los índices que se pasan de 13 (materiales) o de 3 (BD fees) quedan a NULL
solos: el `JOIN` con el mapa los descarta.

Revision ID: b2e5c8d16f22
Revises: b1d4a7c05e11
Create Date: 2026-08-18
"""
import sqlalchemy as sa
from alembic import op

revision = 'b2e5c8d16f22'
down_revision = 'b1d4a7c05e11'
branch_labels = None
depends_on = None


# Los external_id van EN ORDEN. Copiados a mano a propósito: una migración que
# importa código de aplicación se rompe cuando ese código evoluciona.
HUECOS_BDF = ['bldg-fees-1', 'bldg-fees-2', 'bldg-dept-fees-3']
HUECOS_MAT = [
    'materials-purchased-1-2', 'materials-purchased-2', 'materials-purchased-3',
    'material-purchase-4', 'material-purchase-5', 'material-purchase-6',
    'material-purchase-7', 'material-purchase-8', 'material-purchase-9',
    'material-purchase-10', 'material-purchase-11', 'material-purchase-12',
    'material-purchase-13',
]


def _valores(huecos):
    return ", ".join(f"({i}, '{e}')" for i, e in enumerate(huecos))


SQL_BDF = f"""
WITH num AS (
  SELECT "ID_EstimateCost" AS pk,
         row_number() OVER (PARTITION BY "ID_Jobs" ORDER BY "ID_EstimateCost") - 1 AS idx
  FROM estimate_cost
  WHERE "Cost_type" = 'BDF' AND "Status" = 'Approved' AND "ID_Jobs" IS NOT NULL
), mapa(idx, ext) AS (VALUES {_valores(HUECOS_BDF)})
UPDATE estimate_cost e
   SET podio_field = mapa.ext
  FROM num JOIN mapa ON mapa.idx = num.idx
 WHERE e."ID_EstimateCost" = num.pk AND e.podio_field IS NULL
"""

# El pool de 13 lo comparten DOS tablas. El row_number sobre el UNION replica
# exactamente el orden de `qid_mapper`: primero los alquileres, luego las compras.
SQL_POOL = f"""
WITH pool AS (
  SELECT 'EC' AS t, "ID_EstimateCost" AS pk, "ID_Jobs", 0 AS grupo, "ID_EstimateCost" AS orden
    FROM estimate_cost
   WHERE "Cost_type" = 'Rent' AND "Status" = 'Approved' AND "ID_Jobs" IS NOT NULL
  UNION ALL
  SELECT 'P', "ID_Purchase", "ID_Jobs", 1, "ID_Purchase"
    FROM purchase WHERE "ID_Jobs" IS NOT NULL
), num AS (
  SELECT t, pk, row_number() OVER (PARTITION BY "ID_Jobs" ORDER BY grupo, orden) - 1 AS idx
    FROM pool
), mapa(idx, ext) AS (VALUES {_valores(HUECOS_MAT)})
UPDATE {{tabla}} d
   SET podio_field = mapa.ext
  FROM num JOIN mapa ON mapa.idx = num.idx
 WHERE d."{{pk}}" = num.pk AND num.t = '{{marca}}' AND d.podio_field IS NULL
"""


def upgrade() -> None:
    conn = op.get_bind()
    tocadas = conn.execute(sa.text(SQL_BDF)).rowcount
    tocadas += conn.execute(sa.text(
        SQL_POOL.format(tabla="estimate_cost", pk="ID_EstimateCost", marca="EC"))).rowcount
    tocadas += conn.execute(sa.text(
        SQL_POOL.format(tabla="purchase", pk="ID_Purchase", marca="P"))).rowcount

    restantes = conn.execute(sa.text("""
        SELECT (SELECT count(*) FROM estimate_cost
                 WHERE podio_field IS NULL AND "ID_Jobs" IS NOT NULL
                   AND "Status" = 'Approved' AND "Cost_type" IN ('BDF', 'Rent'))
             + (SELECT count(*) FROM purchase
                 WHERE podio_field IS NULL AND "ID_Jobs" IS NOT NULL)
    """)).scalar()

    print(f"[relleno de huecos] {tocadas} filas asignadas · {restantes} siguen a NULL "
          f"(caen al reparto posicional, que es el comportamiento de siempre)")


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text('UPDATE estimate_cost SET podio_field = NULL'))
    conn.execute(sa.text('UPDATE purchase SET podio_field = NULL'))
