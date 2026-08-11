"""re-backfill de podio_app_year desde ID_Jobs, con aserción de cierre

Revision ID: a7c1f3e94b20
Revises: d95e922a318d
Create Date: 2026-08-10 21:05:00.000000

`2f9e5eb00eef` ya está corregida en su sitio, así que en PRODUCCIÓN correrá bien
la primera vez y esta migración no encontrará nada que hacer. Existe por dos
motivos:

1. **Develop** (y cualquier entorno donde `2f9e5eb00eef` ya se aplicó con el
   backfill viejo) arrastra el estado malo: allí hay filas con `podio_app_year`
   NULL o con el año de `Date_assigned` en vez del de su app.
2. Es la **puerta**: la aserción del final impide que un año imposible llegue a
   producción. Que falle la migración es mejor que descubrirlo cuando
   `get_job_app_credentials` lance un ValueError en caliente.

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a7c1f3e94b20'
down_revision: Union[str, Sequence[str], None] = 'd95e922a318d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mismo SQL que `2f9e5eb00eef`, duplicado a propósito: una migración no debe
# importar de `src/`, o deja de estar congelada. `test_regla_anio_unica.py`
# comprueba que esta regla y la de Python no divergen.
DIGITO = """substring(substring("ID_Jobs" from 4) from '[0-9]')"""

SQL_BACKFILL = f"""
UPDATE jobs
   SET podio_app_year = 2020 + ({DIGITO})::int
 WHERE {DIGITO} IN ('3','4','5','6')
   AND podio_app_year IS DISTINCT FROM 2020 + ({DIGITO})::int
"""

# 1. Ningún año imposible. El backfill viejo dejaba 56 filas en 2022 y
#    `get_job_app_credentials` lanza para cualquier año fuera de JOB_YEARS.
#    El techo se calcula, no se clava: clavar 2026 mete el límite de JOB_YEARS
#    en el historial del esquema y rompe la migración en enero de 2027.
SQL_ASSERT_RANGO = """
SELECT count(*) FROM jobs
 WHERE podio_app_year IS NOT NULL
   AND (podio_app_year < 2023
        OR podio_app_year > EXTRACT(YEAR FROM now())::int + 1)
"""

# 2. Ninguna fila venida de Podio puede quedarse sin año: sin él desaparece de
#    cualquier vista filtrada por año y su sync saliente no sale nunca.
#    Se acota a `podio_item_id IS NOT NULL` porque los tests siembran jobs con
#    IDs tipo `QID8xxxxx`, cuyo dígito no es un año configurado; sin acotar, esa
#    basura de pruebas tumbaría la migración en develop.
SQL_ASSERT_SIN_ANIO = f"""
SELECT count(*) FROM jobs
 WHERE podio_item_id IS NOT NULL
   AND coalesce(podio_app_year,
                CASE WHEN {DIGITO} IN ('3','4','5','6')
                     THEN 2020 + ({DIGITO})::int END) IS NULL
"""


def upgrade() -> None:
    conexion = op.get_bind()
    corregidas = conexion.exec_driver_sql(SQL_BACKFILL).rowcount
    print(f"[a7c1f3e94b20] filas con podio_app_year corregido: {corregidas}")

    fuera_de_rango = conexion.exec_driver_sql(SQL_ASSERT_RANGO).scalar()
    if fuera_de_rango:
        raise RuntimeError(
            f"{fuera_de_rango} jobs quedaron con un podio_app_year imposible "
            f"(fuera de 2023..año+1). Ese era exactamente el fallo del backfill "
            f"viejo: 56 filas en 2022, un año que get_job_app_credentials no "
            f"tiene configurado. Se aborta antes de enviarlo a producción."
        )

    sin_anio = conexion.exec_driver_sql(SQL_ASSERT_SIN_ANIO).scalar()
    if sin_anio:
        raise RuntimeError(
            f"{sin_anio} jobs con podio_item_id se quedaron sin año derivable. "
            f"Desaparecerían de cualquier filtro por año del panel y su sync "
            f"saliente nunca saldría. Revisar sus ID_Jobs antes de continuar."
        )


def downgrade() -> None:
    """No-op a propósito.

    Deshacer el re-backfill sería volver a poner años equivocados donde ahora
    hay años correctos. La columna la quita `2f9e5eb00eef` si se baja hasta ahí.
    """
