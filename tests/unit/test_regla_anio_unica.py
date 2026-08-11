"""La regla del año tiene tres consumidores y no pueden discrepar.

Python (`anio_desde_id_jobs`), SQL de migración (`sql_anio_desde_id`) y expresión
de consulta (`expr_anio_app`) calculan lo mismo. El fallo que este test existe
para evitar no es que la regla esté mal, es que se **bifurque**: alguien arregla
el filtro y no la migración, y a partir de ahí el panel y la BD cuentan cosas
distintas sin que nada falle.

El SQL se prueba sobre una `TEMP TABLE ... ON COMMIT DROP`: vive en la conexión,
no toca el esquema compartido de develop.
"""
import pytest
from sqlalchemy import text

from src.utils.job_app_year import (
    anio_desde_id_jobs,
    resolver_anio_app,
    sql_anio_desde_id,
)

# (ID_Jobs, año esperado). Los casos patológicos son los tres del medio.
MATRIZ = [
    ("QID50001", 2025),
    ("PTL30001", 2023),
    ("PAR60039", 2026),
    ("QID40012", 2024),
    ("QID-I60001", 2026),   # job local: el 4.º carácter es '-', no un dígito
    ("PTL-I60001", 2026),
    ("PAR-I60001", 2026),
    ("QID80001", None),     # 8 no es año configurado (jobs sembrados por tests)
    ("QID", None),          # solo prefijo
    ("QIDABC", None),       # sin dígito
    ("", None),
    (None, None),
]


@pytest.mark.parametrize("id_jobs,esperado", MATRIZ)
def test_python(id_jobs, esperado):
    assert anio_desde_id_jobs(id_jobs) == esperado


def test_el_sql_da_lo_mismo_que_python(db_session):
    db_session.exec(text(
        'CREATE TEMP TABLE _anio_tmp ("ID_Jobs" text) ON COMMIT DROP'))
    reales = [(i, e) for i, e in MATRIZ if i]
    for id_jobs, _ in reales:
        db_session.exec(
            text('INSERT INTO _anio_tmp VALUES (:v)').bindparams(v=id_jobs))

    filas = db_session.exec(text(
        f'SELECT "ID_Jobs", {sql_anio_desde_id()} AS anio FROM _anio_tmp')).all()

    calculado = {i: a for i, a in filas}
    assert calculado == {i: e for i, e in reales}
    db_session.rollback()  # suelta la temp table


def test_la_expresion_de_consulta_da_lo_mismo_que_python(db_session):
    """Contra los jobs REALES de develop, no contra una matriz inventada."""
    from sqlmodel import select

    from src.models.JobModel import Job
    from src.utils.job_app_year import expr_anio_app

    filas = db_session.exec(
        select(Job.ID_Jobs, Job.podio_app_year, expr_anio_app())).all()
    assert filas, "develop tiene que tener jobs"

    discrepan = [
        (id_jobs, persistido, sql)
        for id_jobs, persistido, sql in filas
        if (persistido if persistido is not None else anio_desde_id_jobs(id_jobs)) != sql
    ]
    assert not discrepan, f"la expresión SQL discrepa de Python en {discrepan[:5]}"


def test_el_coalesce_rescata_los_ptl_sin_año_persistido(db_session):
    """C3: el backfill viejo dejó `podio_app_year` NULL en todos los PTL.

    Filtrar por la columna pelada los haría desaparecer del panel. Con la
    expresión, ninguno se queda sin año.
    """
    from sqlmodel import func, select

    from src.models.JobModel import Job
    from src.utils.job_app_year import expr_anio_app

    sin_anio = db_session.exec(
        select(func.count()).select_from(Job).where(expr_anio_app().is_(None))
    ).one()
    assert sin_anio == 0, f"{sin_anio} jobs se quedarían fuera de cualquier filtro por año"


def test_el_persistido_gana_sobre_el_derivado():
    class _Job:
        podio_app_year = 2024
        ID_Jobs = "QID60001"

    assert resolver_anio_app(_Job()) == 2024


def test_ya_no_se_usa_date_assigned():
    """Antes `resolve_job_app_year` caía a `Date_assigned.year`.

    Era la rama que mandaba los updates a la app del año equivocado: en 88 jobs
    de producción el año de `Date_assigned` no es el de su app.
    """
    from datetime import datetime

    class _Job:
        podio_app_year = None
        ID_Jobs = "QID60001"
        Date_assigned = datetime(2023, 3, 5)

    assert resolver_anio_app(_Job()) == 2026  # el de ID_Jobs, no el de la fecha


def test_sin_dato_no_se_inventa_un_año():
    """Nunca now(): sin dato, no se sincroniza (queda en PodioFailedSync)."""
    class _Job:
        podio_app_year = None
        ID_Jobs = None

    assert resolver_anio_app(_Job()) is None
