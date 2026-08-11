"""Las filas y el `total` de la lista de jobs tienen que contar lo mismo.

Estaban escritos dos veces y llevaban meses divergiendo: las filas resolvían
`?status=A,B` con `in_()` y el conteo con `ilike('A,B')`, que no casa con nada.
La respuesta traía filas y `total: 0`.

Eso importa más de lo que parece: el número que el cliente mira para dar la
paridad por buena es justo ese `total`.

El segundo tema es el año. Ahora sale de `podio_app_year` (a qué app de Podio
pertenece el item), no de `Date_assigned`. Y tiene que salir con el `coalesce` a
`ID_Jobs`, porque la columna está NULL en todos los PTL — filtrar por la columna
pelada los haría desaparecer del panel.
"""
import pytest

from src.config import JOB_TYPES, JOB_YEARS

RUTAS = ["/jobs/jobs_table", "/jobs/"]


def _pedir(client, headers, ruta, **params):
    from urllib.parse import urlencode

    resp = client.get(f"{ruta}?{urlencode(params)}", headers=headers)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    return resp.get_json()


@pytest.mark.parametrize("ruta", RUTAS)
def test_status_con_coma_no_devuelve_total_cero(client, admin_headers, ruta):
    """El bug vivo: filas con `in_()`, conteo con `ilike('A,B')`."""
    cuerpo = _pedir(client, admin_headers, ruta,
                    status="Invoiced,Paid", page=1, limit=10)

    assert cuerpo["total"] >= len(cuerpo["results"]), (
        f"{ruta} devolvió {len(cuerpo['results'])} filas con total={cuerpo['total']}")
    if cuerpo["results"]:
        assert cuerpo["total"] > 0


@pytest.mark.parametrize("ruta", RUTAS)
def test_el_status_ya_no_es_sensible_a_mayusculas(client, admin_headers, ruta):
    """`in_()` distinguía mayúsculas y `ilike` no: tampoco coincidían entre sí."""
    a = _pedir(client, admin_headers, ruta, status="paid", limit=1)
    b = _pedir(client, admin_headers, ruta, status="PAID", limit=1)
    assert a["total"] == b["total"]


@pytest.mark.parametrize("ruta", RUTAS)
@pytest.mark.parametrize("filtros", [
    {},
    {"type": "QID"},
    {"type": "PTL"},
    {"type": "PAR"},
    {"year": 2025},
    {"type": "QID", "year": 2025},
    {"status": "Invoiced,Paid"},
    {"search": "a"},
])
def test_las_filas_paginadas_suman_exactamente_el_total(
        client, admin_headers, ruta, filtros):
    """La red de verdad: recorre todas las páginas y compara con `total`.

    Cualquier divergencia futura entre los dos WHERE la rompe, sea cual sea el
    filtro que la cause.
    """
    primera = _pedir(client, admin_headers, ruta, page=1, limit=20, **filtros)
    total = primera["total"]

    vistas, pagina = len(primera["results"]), 1
    while vistas < total and pagina < 25:
        pagina += 1
        vistas += len(
            _pedir(client, admin_headers, ruta, page=pagina, limit=20,
                   **filtros)["results"])

    assert vistas == total, (
        f"{ruta} con {filtros}: total dice {total} pero paginando salen {vistas}")


def test_el_filtro_por_año_incluye_los_ptl(client, admin_headers):
    """C3: `podio_app_year` está NULL en todos los PTL.

    Con la columna pelada este filtro daría 0 y los PTL desaparecerían del
    panel. Con el `coalesce` a `ID_Jobs` salen.
    """
    total_ptl = _pedir(client, admin_headers, "/jobs/jobs_table",
                       type="PTL", limit=1)["total"]
    assert total_ptl > 0, "develop tiene que tener PTL"

    por_año = sum(
        _pedir(client, admin_headers, "/jobs/jobs_table",
               type="PTL", year=a, limit=1)["total"]
        for a in JOB_YEARS)
    assert por_año == total_ptl, (
        f"{total_ptl - por_año} PTL se quedan fuera de todos los años")


@pytest.mark.parametrize("tipo", JOB_TYPES)
def test_ningun_job_se_queda_sin_año(client, admin_headers, tipo):
    """La suma por años tiene que dar el total del tipo, para los tres."""
    total = _pedir(client, admin_headers, "/jobs/jobs_table",
                   type=tipo, limit=1)["total"]
    por_año = sum(
        _pedir(client, admin_headers, "/jobs/jobs_table",
               type=tipo, year=a, limit=1)["total"]
        for a in JOB_YEARS)
    assert por_año == total


def test_las_dos_rutas_de_lista_dan_el_mismo_total(client, admin_headers):
    """`GET /jobs/` ignoraba `year` y `status` en silencio.

    Quien verificara la paridad con curl contra `/jobs/?type=QID&year=2025`
    recibía todos los QID de todos los años y concluía una divergencia
    catastrófica que no existía.
    """
    for filtros in ({"type": "QID", "year": 2025},
                    {"type": "PTL", "year": 2026},
                    {"status": "Invoiced,Paid"}):
        a = _pedir(client, admin_headers, "/jobs/", limit=1, **filtros)["total"]
        b = _pedir(client, admin_headers, "/jobs/jobs_table", limit=1, **filtros)["total"]
        assert a == b, f"{filtros}: /jobs/ dice {a} y jobs_table dice {b}"


def test_jobs_table_expone_el_año_de_la_app(client, admin_headers):
    """Sin esto el panel tiene que adivinar el año desde las fechas."""
    cuerpo = _pedir(client, admin_headers, "/jobs/jobs_table", limit=5)
    assert cuerpo["results"], "develop tiene que tener jobs"

    for fila in cuerpo["results"]:
        assert "podio_app_year" in fila
        assert fila["podio_app_year"] in JOB_YEARS


def test_un_año_invalido_da_400_y_no_un_patron_raro(client, admin_headers):
    """`by-type-year` construía `QIDc%` a partir de `?year=abc`."""
    resp = client.get("/jobs/by-type-year?type=QID&year=abc", headers=admin_headers)
    assert resp.status_code == 400
