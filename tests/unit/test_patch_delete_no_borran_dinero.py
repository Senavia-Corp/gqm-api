"""Tres caminos dejaban un importe mal o borrado en Podio, que es la fuente de verdad.

1. `map_chorder_patch_to_podio` solo metia el campo `if ChangeOrderFormula is
   not None`. Con None devolvia `{}`, la ruta hacia `if payload:` y SALTABA la
   llamada a Podio respondiendo 200: el CO quedaba NULL en la BD y el importe
   VIEJO intacto en Podio, sin fila en la dead-letter.

   No es teorico. El panel manda `ChangeOrderFormula: newFormula || null`
   (ChangeOrdersSection.tsx:324) y `newFormula` sale de `parseFloat(...) || 0`,
   asi que ESCRIBIR 0 PARA LIMPIAR manda `null` y dispara este camino exacto.

2. Lo mismo en `map_order_patch_to_podio` con Formula / Ptl_hd_materials / Notes.

3. `map_order_delete_to_podio` emitia `[]` sin mirar si queda OTRA Order en el
   mismo slot. Y las hay: en produccion, job_podio_id 3304340068 (PAR6095) tiene
   ORD68994 y ORD69726 las dos en `tech-1-ptl-original-pricing`. Borrar una
   vaciaba el campo y borraba de Podio el importe de la que sigue viva.

Que 1 y 2 son bugs lo prueba el mismo fichero: el mapper de CREATE si escribe
`[]` para limpiar, y el POST tiene un guard que devuelve 400.
"""
import pytest

from src.utils.mappers.to_podio.order_changeorder_mappers import (
    map_chorder_delete_to_podio,
    map_chorder_patch_to_podio,
    map_order_delete_to_podio,
    map_order_patch_to_podio,
)


class _CO:
    podio_field = "change-order-1"

    def __init__(self, formula=None):
        self.ChangeOrderFormula = formula


class _Order:
    ID_Order = "ORD68994"
    job_podio_id = "3304340068"
    tech_field = "tech-1-ptl-original-pricing"

    def __init__(self, formula=None, hd=None, notes=None, id_order="ORD68994"):
        self.Formula = formula
        self.Ptl_hd_materials = hd
        self.Notes = notes
        self.ID_Order = id_order


class _SesionConSuperviviente:
    def __init__(self, superviviente):
        self._s = superviviente

    def exec(self, _stmt):
        return self

    def first(self):
        return self._s


# --------------------------------------------------------------------------
# 1. Change Order: limpiar tiene que LIMPIAR en Podio
# --------------------------------------------------------------------------
def test_limpiar_la_formula_escribe_vacio_en_podio():
    """El caso del panel: escribir 0 llega como null."""
    payload = map_chorder_patch_to_podio(
        _CO(formula=None), "QID", None,
        campos_tocados={"ChangeOrderFormula"})

    assert payload, (
        "devolvio {} : la ruta salta la llamada y el importe VIEJO se queda "
        "en Podio, que es la fuente de verdad")
    assert payload["change-order-1"] == [], payload


def test_sin_campos_tocados_un_none_sigue_significando_limpiar():
    """Llamado EXACTAMENTE como lo hacia el codigo viejo (sin el parametro).

    Asi la demostracion contra el baseline es del COMPORTAMIENTO y no de la
    firma: alli esto devuelve `{}` y la ruta se calla; aqui devuelve `[]` y
    Podio se entera.
    """
    payload = map_chorder_patch_to_podio(_CO(formula=None), "QID", None)
    assert payload != {}, (
        "devolvio {} : la ruta hace `if payload:`, salta la llamada a Podio y "
        "responde 200 con el importe VIEJO intacto en la fuente de verdad")
    assert payload["change-order-1"] == []


def test_sin_campos_tocados_una_order_tambien_limpia():
    payload = map_order_patch_to_podio(_Order(formula=None), "PTL", None)
    assert payload.get("tech-1-ptl-original-pricing") == [], payload


def test_un_patch_que_no_toca_el_dinero_no_lo_borra():
    """La otra mitad: sin esto, limpiar de mas seria igual de destructivo."""
    payload = map_chorder_patch_to_podio(
        _CO(formula=None), "QID", None, campos_tocados={"Name"})
    assert payload == {}, f"un PATCH de Name toco el dinero: {payload}"


def test_un_importe_normal_sigue_yendo_como_numero():
    payload = map_chorder_patch_to_podio(
        _CO(formula=330), "QID", None, campos_tocados={"ChangeOrderFormula"})
    assert payload["change-order-1"] == 330.0


def test_el_create_ya_lo_hacia_bien():
    """Referencia: por esto se sabe que el PATCH era el raro."""
    payload = map_chorder_delete_to_podio(_CO(), "QID")
    assert payload["change-order-1"] == []


# --------------------------------------------------------------------------
# 2. Order: los tres campos
# --------------------------------------------------------------------------
def test_limpiar_la_formula_de_una_order_escribe_vacio():
    payload = map_order_patch_to_podio(
        _Order(formula=None), "PTL", None, campos_tocados={"Formula"})
    assert payload.get("tech-1-ptl-original-pricing") == [], payload


def test_una_order_sin_cambios_de_dinero_no_toca_dinero():
    payload = map_order_patch_to_podio(
        _Order(formula=None), "PTL", None, campos_tocados={"Title"})
    assert "tech-1-ptl-original-pricing" not in payload, payload


# --------------------------------------------------------------------------
# 3. DELETE con otra Order en el mismo slot
# --------------------------------------------------------------------------
def test_borrar_una_order_no_borra_el_importe_de_la_que_queda():
    """El caso REAL de PAR6095: ORD68994 y ORD69726 comparten slot."""
    viva = _Order(formula=330, id_order="ORD69726")
    payload = map_order_delete_to_podio(
        _Order(formula=110, id_order="ORD68994"), "PTL",
        _SesionConSuperviviente(viva))

    assert payload["tech-1-ptl-original-pricing"] == 330.0, (
        "vacio el campo en Podio y se llevo por delante el importe de la Order "
        f"que sigue viva: {payload}")


def test_si_no_queda_ninguna_el_campo_si_se_limpia():
    payload = map_order_delete_to_podio(
        _Order(formula=110), "PTL", _SesionConSuperviviente(None))
    assert payload["tech-1-ptl-original-pricing"] == []


def test_sin_sesion_conserva_el_comportamiento_antiguo():
    payload = map_order_delete_to_podio(_Order(formula=110), "PTL")
    assert payload["tech-1-ptl-original-pricing"] == []


# --------------------------------------------------------------------------
# Las rutas dejan de tener el `if payload:` mudo
# --------------------------------------------------------------------------
@pytest.mark.parametrize("modulo,funcion", [
    ("src.routes.ChangeOrder", "update_changeOr"),
    ("src.routes.Order", "update_order"),
])
def test_la_ruta_no_calla_ante_un_payload_vacio(modulo, funcion):
    import ast
    import importlib
    import inspect
    import textwrap

    mod = importlib.import_module(modulo)
    fn = getattr(mod, funcion, None)
    if fn is None:
        candidatos = [n for n in dir(mod) if "update" in n.lower()]
        pytest.fail(f"no existe {funcion} en {modulo}; hay {candidatos}")

    fuente = inspect.getsource(getattr(fn, "__wrapped__", fn))
    codigo = ast.unparse(ast.parse(textwrap.dedent(fuente)))

    assert "empty_podio_payload" in codigo, (
        "sigue el `if payload:` mudo: un payload vacio salta la llamada a "
        "Podio y responde 200 dejando el importe viejo")
    assert "campos_tocados" in codigo, (
        "la ruta no le dice al mapper que campos trajo el PATCH")
