"""El pipeline por miembro tiene que mostrar solo lo que dice su titulo.

La seccion «P/Quote Pipeline per Member» filtraba por `PENDING_ALL` y unia
`job_member` por los dos roles. Resultado medido en produccion el 22-ago-2026:
1.843 filas de las que 1.697 eran `Waiting for Approval`, y jobs repetidos bajo
dos miembros distintos. Ver `tests/unit/test_member_pipeline_estados.py` para la
parte estructural, que corre sin base de datos.

Estos tests son de COMPORTAMIENTO y necesitan el arnes completo: `.env` con
`DATABASE_URL` de Neon develop, `APP_ENV=test` y los usuarios de
`scripts/seed_rbac.py`. Sin eso `tests/conftest.py` aborta la sesion entera.

Los asserts son invariantes, no cifras: develop tiene otro dataset que
produccion y fijar numeros absolutos aqui seria un test que miente.
"""
import pytest

from src.config import JOB_TYPES

RUTA = "/job_metrics/member-pipeline"


def _pedir(client, headers, **params):
    from urllib.parse import urlencode

    resp = client.get(f"{RUTA}?{urlencode(params)}", headers=headers)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    return resp.get_json()


def _estados_permitidos(cuerpo):
    """`pipeline_statuses` es una lista con un tipo concreto y un dict con ALL."""
    ps = cuerpo["pipeline_statuses"]
    return set(ps) if isinstance(ps, list) else {e for v in ps.values() for e in v}


def test_exige_autenticacion(client):
    assert client.get(RUTA).status_code in (401, 403)


@pytest.mark.parametrize("tipo", JOB_TYPES + ["ALL"])
def test_ningun_job_sale_con_un_estado_que_no_declara(client, admin_headers, tipo):
    """El invariante que el bug rompia: lo mostrado ⊆ lo prometido."""
    cuerpo = _pedir(client, admin_headers, type=tipo, page=1, limit=50)
    permitidos = _estados_permitidos(cuerpo)

    for miembro in cuerpo["members"]:
        for job in miembro["jobs"]:
            assert job["status"] in permitidos, (
                f"type={tipo}: {job['job_id']} sale con «{job['status']}», que no "
                f"esta en pipeline_statuses {sorted(permitidos)}"
            )


def test_par_dice_que_no_tiene_etapa_de_cotizacion(client, admin_headers):
    cuerpo = _pedir(client, admin_headers, type="PAR")

    assert cuerpo["members"] == [], "PAR no puede traer cotizaciones"
    assert cuerpo.get("reason") == "no_quote_stage", (
        "una lista vacia sin explicacion se lee como «se rompio algo»; PAR tiene "
        "que decir POR QUE esta vacio"
    )


@pytest.mark.parametrize("tipo", JOB_TYPES + ["ALL"])
def test_un_job_no_aparece_dos_veces_bajo_el_mismo_miembro(client, admin_headers, tipo):
    """Antes salia duplicado si el miembro tenia los dos roles en el job."""
    cuerpo = _pedir(client, admin_headers, type=tipo, page=1, limit=50)

    for miembro in cuerpo["members"]:
        ids = [j["job_id"] for j in miembro["jobs"]]
        assert len(ids) == len(set(ids)), (
            f"{miembro['name']} tiene jobs repetidos: "
            f"{sorted({i for i in ids if ids.count(i) > 1})}"
        )


def test_un_job_pertenece_a_un_solo_miembro(client, admin_headers):
    """Con dueno unico, la suma por miembro ES el pipeline. Antes no lo era."""
    cuerpo = _pedir(client, admin_headers, type="ALL", page=1, limit=50)

    duenos = {}
    for miembro in cuerpo["members"]:
        for job in miembro["jobs"]:
            anterior = duenos.setdefault(job["job_id"], miembro["name"])
            assert anterior == miembro["name"], (
                f"{job['job_id']} sale bajo «{anterior}» y bajo «{miembro['name']}»"
            )


@pytest.mark.parametrize("tipo", JOB_TYPES + ["ALL"])
def test_los_totales_del_miembro_cuadran_con_sus_filas(client, admin_headers, tipo):
    cuerpo = _pedir(client, admin_headers, type=tipo, page=1, limit=50)

    for miembro in cuerpo["members"]:
        assert miembro["job_count"] == len(miembro["jobs"]), (
            f"{miembro['name']}: job_count={miembro['job_count']} pero "
            f"{len(miembro['jobs'])} filas"
        )

        montos = [j["amount"] for j in miembro["jobs"] if j["amount"] is not None]
        if montos:
            assert miembro["total_quoted"] == pytest.approx(sum(montos)), (
                f"{miembro['name']}: total_quoted no es la suma de sus montos"
            )
        else:
            assert miembro["total_quoted"] is None, (
                "sin ningun monto el total tiene que ser None, no 0: un 0 se pinta "
                "como «$0.00» y eso es una cifra inventada"
            )


def test_las_paginas_suman_el_total_de_miembros(client, admin_headers):
    """El conteo y la pagina se construyen por separado: es la clase de bug que
    ya se cazo en la lista de jobs (WHERE escrito dos veces)."""
    primera = _pedir(client, admin_headers, type="ALL", page=1, limit=2)
    total = primera["pagination"]["total_members"]

    vistos, pagina = len(primera["members"]), 1
    while vistos < total and pagina < 25:
        pagina += 1
        vistos += len(_pedir(client, admin_headers,
                             type="ALL", page=pagina, limit=2)["members"])

    assert vistos == total, f"paginando salen {vistos} miembros y el total dice {total}"


def test_los_jobs_salen_ordenados_por_fecha_descendente(client, admin_headers):
    """Antes no habia ningun ORDER BY y las filas salian como quisiera la BD."""
    cuerpo = _pedir(client, admin_headers, type="ALL", page=1, limit=50)

    for miembro in cuerpo["members"]:
        fechas = [j["date"] for j in miembro["jobs"] if j["date"] != "—"]
        assert fechas == sorted(fechas, reverse=True), (
            f"{miembro['name']} trae las fechas desordenadas: {fechas[:6]}"
        )
