"""El mapa de cuotas se genera desde el esquema de Podio, no se teclea.

La prueba clave es la primera: regenera el mapa desde el fixture y lo compara
con el artefacto versionado. Si alguien lo edita a mano, falla. Es lo que hace
que emitir JSON en vez de un `.py` generado tenga sentido.

El fixture (`tests/fixtures/esquema_pagos.json`) es el recorte de las secciones
`*PAYMENT SCHEDULE*` de los 12 volcados de producción, porque los volcados
completos viven fuera del repo (`~/outputs/gqm-auditoria-campos/esquema/`).
"""
import json
import pathlib

import pytest

from src.utils.mappers.from_podio import payment_slots

RAIZ = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = RAIZ / "tests/fixtures/esquema_pagos.json"
ARTEFACTO = RAIZ / "src/utils/mappers/from_podio/payment_slots.json"


def _regenerar_desde_fixture() -> dict:
    """Ejecuta el generador sobre el fixture, no sobre `~/outputs`."""
    import importlib.util
    import tempfile

    spec = importlib.util.spec_from_file_location(
        "generar_mapa_pagos", RAIZ / "scripts/generar_mapa_pagos.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)

    datos = json.loads(FIXTURE.read_text())
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        for v in datos["volcados"]:
            (d / v["_fichero"]).write_text(json.dumps(v))
        return gen.construir_artefacto(d)


def test_el_artefacto_coincide_con_el_generador():
    """Si esto falla, o el esquema de Podio cambió o alguien editó el JSON."""
    assert _regenerar_desde_fixture() == json.loads(ARTEFACTO.read_text())


def test_no_emite_ningun_campo_calculado():
    """`TECH n Adj Formula` y `Total (Left to) Pay` los calcula Podio. Si no
    están en el artefacto, es imposible escribirlos por accidente."""
    calculados = {"calculation", "calculation-9", "tech-3-final-formula",
                  "total-left-to-pay-tech-3"}
    art = json.loads(ARTEFACTO.read_text())
    emitidos = {ext
                for app in art["apps"].values()
                for anio in app["anios"].values()
                for tech in anio["techs"].values()
                for ext in tech["cuotas"].values()}
    assert not (emitidos & calculados)
    assert not any(e.startswith("total-left-to-pay") for e in emitidos)


def test_qid_tecnico_1_tiene_once_cuotas():
    """Oráculo escrito a mano: el motivo de que tres columnas no bastaran."""
    mapa = payment_slots.mapa_pagos("QID", 2026)[1]
    assert len(mapa) == 11
    assert mapa[1] == "check-amount-payment-1"
    assert mapa[3] == "check-amount-payment-3"
    assert mapa[4] == "tech-1-payment-4"
    assert mapa[11] == "tech-1-payment-11"


def test_qid_tecnico_6_usa_money_4_y_money_5():
    """La irregularidad que hace imposible teclear el mapa a mano."""
    mapa = payment_slots.mapa_pagos("QID", 2026)[6]
    assert mapa[2] == "money-4"
    assert mapa[3] == "money-5"


def test_los_materiales_de_ptl_no_se_confunden_con_cuotas():
    """`Tech N - H.D. / Materials` es `money` y vive DENTRO de la sección de
    pagos, pero no es un cheque."""
    todos = {ext
             for anio in json.loads(ARTEFACTO.read_text())["apps"]["PTL"]["anios"].values()
             for tech in anio["techs"].values()
             for ext in tech["cuotas"].values()}
    assert "home-depot-materials" not in todos
    assert "tech-2-hd-materials" not in todos


def test_el_numero_de_cheque_no_recoge_res_ind():
    """`RES/IND` es `text` y cae dentro de una sección de técnico en PAR."""
    art = json.loads(ARTEFACTO.read_text())
    cheques = {tech["check_numbers"]
               for app in art["apps"].values()
               for anio in app["anios"].values()
               for tech in anio["techs"].values()}
    assert "title" not in cheques


def test_reproduce_el_mapa_manual_de_par_2026():
    """No-regresión sobre el propio generador: el mapa PAR que había escrito a
    mano tiene que salir igual (para los técnicos que 2026 sí tiene)."""
    esperado = {
        1: ["check-amount-payment-1", "check-amount-payment-2", "check-amount-payment-3"],
        2: ["check-amount-payment-1-2", "check-amount-payment-2-2", "check-amount-payment-3-2"],
        3: ["tech-3-payment-1", "tech-3-payment-2"],
        4: ["tech-4-payment-1", "tech-4-payment-2"],
    }
    mapa = payment_slots.mapa_pagos("PAR", 2026)
    assert {t: [c[n] for n in sorted(c)] for t, c in mapa.items()} == esperado


def test_las_colisiones_de_etiqueta_quedan_registradas():
    """QID 2023 tiene dos `money` con la etiqueta `Tech 15 - Payment 1`."""
    avisos = json.loads(ARTEFACTO.read_text())["avisos"]
    assert any(a["tech"] == 15 and a["anio"] == 2023 for a in avisos)
    assert all("resolucion" in a for a in avisos)


@pytest.mark.parametrize("tipo, esperado", [("QID", True), ("PAR", True), ("PTL", False)])
def test_ptl_apagado_como_dato_no_como_condicional(tipo, esperado):
    assert payment_slots.habilitado(tipo) is esperado
