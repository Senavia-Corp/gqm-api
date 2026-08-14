"""AVG TARGET RETURN se promediaba sobre un denominador de una fila.

`func.avg(case((status in ACTIVE_STATUSES, Gqm_target_return), else_=None))`
parecía razonable, pero `ACTIVE_STATUSES` son solo 4 estados (in-progress +
Invoiced) y `AVG` de SQL ignora los NULL. El denominador real era «activo **y**
con valor», que en producción colapsaba a una sola fila en celdas enteras:

- 2023/QID mostraba **-3764.3 %**, que es literalmente el único job que quedaba:
  `QID3221`, con `Gqm_target_return = -37.6429` (formula $44.023 contra un target
  sold de $630 — dato corrupto, ver H-8).
- ALL/PTL mostraba **100.0 %** clavado, también con n=1.

Y cuando no quedaba ninguna fila, `AVG` devolvía NULL y `_safe_float` lo
convertía en `0.0`: un denominador vacío era indistinguible de un 0 % real.

El arreglo usa `AVERAGE_TARGET_RETURN_STATUSES`, que es la constante que este
mismo módulo define **para esta métrica** (in-progress + completed + paid) y que
hasta ahora solo usaba CommunitiesM. El denominador pasa de 1 a 1282 en 2023/QID
y de 1 a 502 en ALL/PTL, con lo que el outlier corrupto deja de mandar.
"""
from src.services.metrics.metrics_shared import (
    ACTIVE_STATUSES,
    AVERAGE_TARGET_RETURN_STATUSES,
    PAID_STATUSES,
)


def test_la_metrica_no_usa_el_conjunto_del_pipeline():
    """`ACTIVE_STATUSES` es para PIPELINE, no para esta métrica.

    Reusarlo es lo que dejaba fuera del promedio a todos los jobs pagados y
    completados — la inmensa mayoría de la cartera.
    """
    assert PAID_STATUSES <= AVERAGE_TARGET_RETURN_STATUSES, (
        "los jobs pagados tienen que entrar en el promedio de retorno"
    )
    assert not (PAID_STATUSES & ACTIVE_STATUSES), (
        "ACTIVE_STATUSES no debería contener pagados: es el conjunto del pipeline"
    )


def test_el_kpi_declara_el_tamano_de_su_denominador(client, admin_headers):
    """Un promedio sobre 1 fila no es un promedio, y hay que poder verlo.

    Contra el código anterior no existía `avg_target_ret_n` en el payload: no
    había forma de saber desde fuera que -3764.3 % era un solo job.
    """
    r = client.get("/job_metrics/status?type=ALL", headers=admin_headers)
    assert r.status_code == 200, r.data

    kpi = r.get_json()["kpi_summary"]
    assert "avg_target_ret_n" in kpi, "el KPI no declara su denominador"
    assert isinstance(kpi["avg_target_ret_n"], int)

    if kpi["avg_target_ret_n"] == 0:
        assert kpi["avg_target_ret"] is None, (
            "sin filas que promediar hay que devolver null, no un 0 % falso"
        )
    else:
        assert kpi["avg_target_ret"] is not None


def test_el_denominador_cubre_la_cartera_no_solo_el_pipeline(client, admin_headers):
    """El denominador tiene que ser del orden de los jobs, no de un puñado.

    En producción con el código viejo era 1 de 1448 en 2023/QID. Este test no
    puede fijar un número absoluto (develop tiene otro dataset), así que fija la
    relación: el promedio de retorno cubre bastantes más jobs que el pipeline.
    """
    todos = client.get("/job_metrics/status?type=ALL", headers=admin_headers)
    assert todos.status_code == 200
    kpi = todos.get_json()["kpi_summary"]

    if kpi["job_count"] == 0:
        return  # dataset vacío: nada que afirmar

    cobertura = kpi["avg_target_ret_n"] / kpi["job_count"]
    assert cobertura > 0.25, (
        f"AVG TARGET RETURN se calcula sobre {kpi['avg_target_ret_n']} de "
        f"{kpi['job_count']} jobs ({cobertura:.1%}). Con ACTIVE_STATUSES esto "
        "bajaba a una sola fila y el KPI lo presentaba como un hecho."
    )
