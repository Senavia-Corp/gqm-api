"""add jobs.podio_app_year

Revision ID: 2f9e5eb00eef
Revises: a16928946379
Create Date: 2026-08-09 01:21:58.632557

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f9e5eb00eef'
down_revision: Union[str, Sequence[str], None] = 'a16928946379'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# El dígito del año es el primero que aparece DESPUÉS del prefijo de 3 letras.
# No es "el 4.º carácter": los jobs locales son `QID-I60001` y ahí el 4.º es '-'.
DIGITO = """substring(substring("ID_Jobs" from 4) from '[0-9]')"""

# Idempotente: el `IS DISTINCT FROM` hace que re-ejecutarlo no toque nada, y el
# `IN` de la primera condición garantiza que el ::int nunca ve basura.
SQL_BACKFILL = f"""
UPDATE jobs
   SET podio_app_year = 2020 + ({DIGITO})::int
 WHERE {DIGITO} IN ('3','4','5','6')
   AND podio_app_year IS DISTINCT FROM 2020 + ({DIGITO})::int
"""


def upgrade() -> None:
    """Añade jobs.podio_app_year (año de la app Podio del item, REG-015).

    Backfill desde `ID_Jobs`, que es el contador nativo de Podio.

    La versión original usaba `EXTRACT(YEAR FROM "Date_assigned")` y estaba mal
    de tres formas distintas, medidas contra producción:

    - **Deja NULL a los 510 PTL.** El 100 % de los PTL tienen `Date_assigned`
      NULL, así que el `WHERE ... IS NOT NULL` los excluye a todos. Con la
      columna vacía, `resolve_job_app_year` devuelve None y su sync a Podio no
      sale nunca.
    - **Da el año equivocado en 88 jobs**, donde la fecha de asignación no cae
      en el año de la app.
    - **56 de esos 88 quedarían en 2022**, y `get_job_app_credentials` lanza
      `ValueError` para cualquier año fuera de `JOB_YEARS`. No era un backfill
      aproximado: era un generador de 500s.

    Se corrige *en su sitio* y no solo al final porque `migrations/env.py:72`
    fija `transaction_per_migration=True`: el estado malo se **commitea**, así
    que si una migración posterior falla, producción se queda con esas 56 filas
    en 2022 y código que revienta al tocarlas.

    Es seguro hacerlo aquí: esta revisión **no se ha aplicado en producción**
    (alembic va por `881887fe30d3`), así que allí correrá por primera vez ya
    corregida. Develop, donde sí está aplicada con el backfill malo, lo arregla
    la migración de re-backfill que va en la cabeza.

    La regla en Python vive en `src/utils/job_app_year.py`; el SQL se duplica
    aquí a propósito para que la migración quede congelada y no dependa de
    `src/`, y `tests/unit/test_regla_anio_unica.py` comprueba que no divergen.
    """
    op.add_column("jobs", sa.Column("podio_app_year", sa.Integer(), nullable=True))
    op.execute(SQL_BACKFILL)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("jobs", "podio_app_year")
