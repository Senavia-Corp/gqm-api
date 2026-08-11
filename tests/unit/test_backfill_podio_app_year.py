"""El SQL de las migraciones del año, probado sin migrar nada.

No hay base de datos de pruebas: `conftest.py` corre contra la Neon develop
compartida, sin esquema propio ni rollback. Y una migración solo se puede
ejercitar una vez — después ya está aplicada. Así que el SQL se prueba sobre una
`TEMP TABLE ... ON COMMIT DROP`, que vive en la conexión y no puede ensuciar el
esquema compartido.

La dependencia va **test → migración** (se importa el `.py` de la revisión con
`importlib`), nunca al revés: la migración sigue congelada y sin importar de
`src/`, y aun así no puede quedarse obsoleta respecto a este test.

Único ajuste: se sustituye el nombre de la tabla. Crear una TEMP TABLE llamada
`jobs` la haría sombrear a la real en el `search_path` de una conexión del pool,
y una fuga dejaría a los tests siguientes leyendo una tabla vacía.
"""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text

VERSIONES = Path(__file__).resolve().parents[2] / "migrations" / "versions"
TMP = "_jobs_anio_tmp"


def _migracion(nombre_fichero: str):
    ruta = VERSIONES / nombre_fichero
    spec = importlib.util.spec_from_file_location(ruta.stem, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


M1 = _migracion("2f9e5eb00eef_add_jobs_podio_app_year.py")
M2 = _migracion("a7c1f3e94b20_rebackfill_podio_app_year.py")


def _sobre_tmp(sql: str) -> str:
    return sql.replace("UPDATE jobs", f"UPDATE {TMP}").replace("FROM jobs", f"FROM {TMP}")


# (ID_Jobs, podio_item_id, podio_app_year inicial, año esperado tras el backfill)
CASOS = [
    ("QID50001", "111", None, 2025),
    ("PTL30001", "112", None, 2023),   # PTL: Date_assigned es NULL al 100 %
    ("PAR60039", "113", None, 2026),
    ("QID-I60001", None, None, 2026),  # job local: el 4.º carácter es '-'
    ("QID30012", "114", 2022, 2023),   # el desastre del backfill viejo, corregido
    ("QID40007", "115", 2024, 2024),   # ya correcto: no se toca
    ("QID80001", None, None, None),    # sembrado por tests: 8 no es año configurado
]


@pytest.fixture
def tabla(db_session):
    db_session.exec(text(
        f'CREATE TEMP TABLE {TMP} ('
        f'  "ID_Jobs" text, podio_item_id text, podio_app_year int'
        f') ON COMMIT DROP'))
    for id_jobs, item, anio, _ in CASOS:
        db_session.exec(
            text(f'INSERT INTO {TMP} VALUES (:i, :p, :a)').bindparams(
                i=id_jobs, p=item, a=anio))
    yield db_session
    db_session.rollback()


def test_el_backfill_deriva_de_id_jobs(tabla):
    tabla.exec(text(_sobre_tmp(M2.SQL_BACKFILL)))

    obtenido = dict(tabla.exec(text(
        f'SELECT "ID_Jobs", podio_app_year FROM {TMP}')).all())
    assert obtenido == {i: e for i, _, _, e in CASOS}


def test_las_dos_migraciones_usan_el_mismo_sql(tabla):
    """M1 y M2 tienen que derivar igual, o produccion y develop divergen."""
    assert M1.SQL_BACKFILL.strip() == M2.SQL_BACKFILL.strip()


def test_el_backfill_es_idempotente(tabla):
    primera = tabla.exec(text(_sobre_tmp(M2.SQL_BACKFILL))).rowcount
    segunda = tabla.exec(text(_sobre_tmp(M2.SQL_BACKFILL))).rowcount

    assert primera == 5, "5 de los 7 casos necesitan corrección"
    assert segunda == 0, "re-ejecutarlo no puede volver a tocar nada"


def test_el_backfill_no_pisa_un_año_ya_correcto(tabla):
    tabla.exec(text(_sobre_tmp(M2.SQL_BACKFILL)))
    anio = tabla.exec(text(
        f'SELECT podio_app_year FROM {TMP} WHERE "ID_Jobs" = \'QID40007\'')).scalar()
    assert anio == 2024


def test_la_asercion_de_rango_atrapa_un_2022(tabla):
    """Es el fallo concreto del backfill viejo: 56 filas en 2022, año que
    `get_job_app_credentials` no tiene configurado y por el que lanza."""
    # Antes del backfill hay un 2022 sembrado a propósito.
    assert tabla.exec(text(_sobre_tmp(M2.SQL_ASSERT_RANGO))).scalar() == 1

    tabla.exec(text(_sobre_tmp(M2.SQL_BACKFILL)))
    assert tabla.exec(text(_sobre_tmp(M2.SQL_ASSERT_RANGO))).scalar() == 0


def test_la_asercion_atrapa_una_fila_de_podio_sin_año(tabla):
    """Un job venido de Podio sin año derivable desaparece de todo filtro."""
    tabla.exec(text(_sobre_tmp(M2.SQL_BACKFILL)))
    assert tabla.exec(text(_sobre_tmp(M2.SQL_ASSERT_SIN_ANIO))).scalar() == 0

    tabla.exec(text(
        f'INSERT INTO {TMP} VALUES (\'QID90001\', \'999\', NULL)'))
    assert tabla.exec(text(_sobre_tmp(M2.SQL_ASSERT_SIN_ANIO))).scalar() == 1


def test_la_asercion_ignora_los_jobs_locales_sin_item(tabla):
    """C5: los IDs sembrados por los tests no pueden tumbar la migración."""
    tabla.exec(text(_sobre_tmp(M2.SQL_BACKFILL)))
    # `QID80001` no tiene año derivable, pero tampoco tiene podio_item_id.
    assert tabla.exec(text(_sobre_tmp(M2.SQL_ASSERT_SIN_ANIO))).scalar() == 0
