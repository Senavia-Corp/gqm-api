"""El reconciliador reescribe dinero: lo que se prueba es que NO se pase.

Repara el defecto medido en producción el 14-ago-2026 — 185 jobs con
`Gqm_formula_pricing = 0` en la BD teniendo Podio un valor real — pero es un
endpoint que hace UPDATE sobre columnas de dinero en producción, así que los
tests van sobre los frenos, no sobre el camino feliz.

`_diff_de_job` es puro y se prueba directo. El endpoint completo necesita Podio,
y eso ya lo cubre la verificación manual contra dev.
"""
import pytest

from src.routes.podio_routes.Paridad import (
    COLUMNAS_DINERO,
    TOLERANCIA,
    _diff_de_job,
    _difiere,
    _token_confirmacion,
)


class _Job:
    """Fila de la BD de mentira."""

    def __init__(self, **kw):
        for c in COLUMNAS_DINERO:
            setattr(self, c, None)
        for k, v in kw.items():
            setattr(self, k, v)


def test_el_caso_real_ptl6035():
    """El job concreto que destapó el defecto.

    Podio: formula 1945, premium 398.26. BD: formula 0, premium 2343.26 (= el
    final entero, porque se derivó con la fórmula en 0).
    """
    job = _Job(Gqm_formula_pricing=0.0, Gqm_premium_in_money=2343.26,
               Gqm_final_sold_pricing=2343.26)
    cambios = _diff_de_job(job, {
        "Gqm_formula_pricing": 1945.0,
        "Gqm_premium_in_money": 398.26,
        "Gqm_final_sold_pricing": 2343.26,
    })

    assert set(cambios) == {"Gqm_formula_pricing", "Gqm_premium_in_money"}, (
        "tiene que tocar fórmula y premium, y dejar el final en paz"
    )
    assert cambios["Gqm_formula_pricing"] == {"bd": 0.0, "podio": 1945.0}


def test_lo_que_ya_coincide_no_se_toca():
    """QID2023 coincide al céntimo en los seis agregados: 0 cambios."""
    job = _Job(Gqm_formula_pricing=15313900.68, Gqm_final_sold_pricing=19174601.28)
    assert _diff_de_job(job, {"Gqm_formula_pricing": 15313900.68,
                              "Gqm_final_sold_pricing": 19174601.28}) == {}


def test_el_ruido_del_float_no_cuenta_como_divergencia():
    """Podio manda texto decimal y la BD guarda float binario.

    Sin tolerancia, medio censo saldría «divergente» y el operador aprendería a
    ignorar el informe.
    """
    job = _Job(Gqm_formula_pricing=1945.0000000001)
    assert _diff_de_job(job, {"Gqm_formula_pricing": 1945.0}) == {}
    assert not _difiere(1945.0000000001, 1945.0)
    assert _difiere(1945.0, 1945.0 + TOLERANCIA * 3)


def test_un_campo_ausente_en_podio_no_es_divergencia():
    """PAR no tiene «Final Sold» en Podio: 27 campos y ninguno.

    Si la ausencia contara como divergencia, el reconciliador pondría a None el
    `Gqm_final_sold_pricing` de los 578 PAR.
    """
    job = _Job(Gqm_final_sold_pricing=1234.0, Gqm_formula_pricing=1.0)
    # Podio trae la fórmula (igual) pero NO trae final_sold: no debe salir nada.
    assert _diff_de_job(job, {"Gqm_formula_pricing": 1.0}) == {}


def test_no_reconcilia_nada_fuera_de_las_columnas_de_dinero():
    """El alcance es la reparación medida, no una reescritura del job."""
    job = _Job()
    job.Project_name = "el de siempre"
    cambios = _diff_de_job(job, {"Project_name": "OTRO NOMBRE",
                                 "Job_status": "Cancelled",
                                 "Date_assigned": "2026-01-01"})
    assert cambios == {}, f"se salió del alcance: {sorted(cambios)}"
    assert job.Project_name == "el de siempre"


def test_el_token_cambia_si_cambia_el_conjunto():
    """Es lo único que impide aplicar un conjunto distinto del que se enseñó."""
    a = _token_confirmacion(["QID6001:['Gqm_formula_pricing']"])
    b = _token_confirmacion(["QID6001:['Gqm_formula_pricing']",
                             "QID6002:['Gqm_premium_in_money']"])
    c = _token_confirmacion(["QID6001:['Gqm_premium_in_money']"])
    assert a != b, "añadir un job tiene que invalidar el token"
    assert a != c, "cambiar QUÉ columna se toca también"
    assert a == _token_confirmacion(["QID6001:['Gqm_formula_pricing']"])


def test_los_importes_de_podio_llegan_como_texto():
    """Podio manda `{"value": "1980.0100"}` — texto, no número.

    Sin convertir, se escribiría la cadena en una columna float. Postgres la
    castea y el UPDATE funciona, pero el objeto en memoria se queda con un str
    hasta el refresh siguiente.
    """
    job = _Job(Gqm_adj_formula_pricing=0.0)
    cambios = _diff_de_job(job, {"Gqm_adj_formula_pricing": "1980.0100"})

    assert cambios["Gqm_adj_formula_pricing"]["podio"] == 1980.01
    assert isinstance(cambios["Gqm_adj_formula_pricing"]["podio"], float), (
        "lo que se va a escribir tiene que ser float, no la cadena de Podio"
    )


def test_texto_igual_al_valor_guardado_no_es_divergencia():
    """«1945.0000» y 1945.0 son el mismo importe."""
    job = _Job(Gqm_formula_pricing=1945.0)
    assert _diff_de_job(job, {"Gqm_formula_pricing": "1945.0000"}) == {}


@pytest.mark.parametrize("bd,podio,esperado", [
    (None, None, False),
    (None, 100.0, True),      # la BD no tiene el dato y Podio sí: hay que traerlo
    (100.0, None, True),
    (0.0, 1945.0, True),      # el defecto
    (0.0, 0.0, False),        # cascarón vacío legítimo
])
def test_matriz_de_nulos(bd, podio, esperado):
    assert _difiere(bd, podio) is esperado
