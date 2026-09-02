"""La medida que decide si se enciende `PODIO_VACIA_SLOTS` tiene que ser exacta.

`/admin/podio/obsoletos_ordenes` produce el número sobre el que se toma una
decisión de producción que mueve agregados de dinero. Si la agregación cuenta
mal, la decisión se toma sobre una cifra inventada — así que la agregación se
comprueba igual que se comprueba el arreglo.

Podio se sustituye por páginas enlatadas: lo que se ejercita aquí es el conteo,
la paginación y que la medida use el MISMO predicado que el arreglo.
"""
import pytest
from sqlmodel import SQLModel, Session, create_engine

import src.models  # noqa: F401
from src.models.ChangeOrderModel import ChangeOrder
from src.models.JobModel import Job
from src.models.OrderModel import Order
from src.routes.podio_routes import Paridad

TABLAS = ("jobs", "order", "change_order", "commission_detail",
          "estimate_cost", "financial_document", "opportunities")


@pytest.fixture()
def sesion():
    motor = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        motor, tables=[SQLModel.metadata.tables[t] for t in TABLAS])
    with Session(motor) as s:
        yield s


class _ServicioPodio:
    """Devuelve las páginas que se le den. `get_items_page(limit=1)` es la sonda."""

    def __init__(self, items, tope_pagina):
        self.items, self.tope = items, tope_pagina
        self.paginas_pedidas = 0

    def get_items_page(self, limit=None, offset=0):
        if limit == 1:
            return {"filtered": len(self.items), "items": self.items[:1]}
        self.paginas_pedidas += 1
        return {"items": self.items[offset:offset + (limit or self.tope)]}


@pytest.fixture()
def podio(monkeypatch):
    def montar(items, tope_pagina=500):
        servicio = _ServicioPodio(items, tope_pagina)
        monkeypatch.setattr(Paridad.podio_jobs_router, "get_readonly_service",
                            lambda tipo, anio: servicio)
        monkeypatch.setattr(Paridad, "TOPE_PAGINA", tope_pagina)
        return servicio
    return montar


def _item(item_id, campos=()):
    return {"item_id": item_id, "app_item_id_formatted": f"QID5{item_id}",
            "fields": [{"external_id": e, "type": "money", "values": [{"value": "1"}]}
                       for e in campos]}


def _sembrar(sesion, ref, id_jobs, tech_field="labor-tech-5", **kw):
    sesion.add(Job(ID_Jobs=id_jobs, podio_item_id=str(ref), Job_type="QID",
                   podio_app_year=2025))
    campos = {"Formula": 500.0, "Adj_formula": 700.0}
    campos.update(kw)
    sesion.add(Order(ID_Order=f"ORD-{ref}", job_podio_id=str(ref),
                     tech_field=tech_field, **campos))
    sesion.commit()


def _medir(sesion, presupuesto=100_000, offset=0):
    return Paridad._obsoletos_de_ordenes(sesion, "QID", 2025, presupuesto, offset)


# --------------------------------------------------------------- lo que cuenta

def test_cuenta_la_order_cuyo_slot_ya_no_esta_en_podio(sesion, podio):
    _sembrar(sesion, 100, "QID50100")
    podio([_item(100, ["tech-1-ptl-original-pricing"])])  # el slot 5 no viene

    resumen, siguiente = _medir(sesion)

    assert siguiente is None and resumen["revisados"] == 1
    assert resumen["orders_a_vaciar"] == 1
    assert resumen["formula_que_se_vacia"] == 500.0
    assert resumen["adj_formula_en_riesgo"] == 700.0
    assert resumen["jobs_afectados"] == 1
    assert resumen["por_slot"] == {"slot-5": 1}


def test_no_cuenta_el_slot_que_si_viene(sesion, podio):
    _sembrar(sesion, 100, "QID50100")
    podio([_item(100, ["labor-tech-5"])])

    resumen, _ = _medir(sesion)

    assert resumen["orders_a_vaciar"] == 0
    assert resumen["formula_que_se_vacia"] == 0
    assert resumen["jobs_afectados"] == 0


def test_la_medida_no_escribe_nada(sesion, podio):
    """`dry_run`: el objeto de la medida es decidir, no reparar."""
    _sembrar(sesion, 100, "QID50100")
    podio([_item(100)])

    _medir(sesion)

    assert not sesion.dirty and not sesion.new and not sesion.deleted
    assert sesion.get(Order, "ORD-100").Formula == 500.0


def test_las_filas_con_datos_locales_se_cuentan_aparte(sesion, podio):
    """Si se mezclaran con las demás, la cifra prometería un vaciado que la
    guarda no va a hacer."""
    _sembrar(sesion, 100, "QID50100", Title="PO-QID50100-01")
    podio([_item(100)])

    resumen, _ = _medir(sesion)

    assert resumen["orders_saltadas_por_datos_locales"] == 1
    assert resumen["orders_a_vaciar"] == 0
    assert resumen["formula_que_se_vacia"] == 0, "prometía dinero que no se mueve"


def test_los_change_orders_de_nivel_orden_se_cuentan(sesion, podio):
    _sembrar(sesion, 100, "QID50100", tech_field="tech-1-ptl-original-pricing")
    sesion.add(ChangeOrder(ID_ChangeOrder="ChO1", job_podio_id="100",
                           podio_field="tech-1-change-order-2",
                           ChangeOrderFormula=90.0, ID_Order="ORD-100"))
    sesion.commit()
    podio([_item(100, ["tech-1-ptl-original-pricing"])])

    resumen, _ = _medir(sesion)

    assert resumen["change_orders_a_vaciar"] == 1


def test_un_item_sin_fila_en_la_bd_no_se_cuenta(sesion, podio):
    """Eso lo mide /parity; mezclarlo aquí sería contar dos cosas distintas."""
    podio([_item(999)])

    resumen, _ = _medir(sesion)

    assert resumen["revisados"] == 0 and resumen["jobs_afectados"] == 0


def test_marca_los_jobs_que_ya_tienen_comision_emitida(sesion, podio):
    from src.models.ComDetailModel import CommissionDetail

    _sembrar(sesion, 100, "QID50100")
    sesion.add(CommissionDetail(ID_ComDetail="CDT1", ID_Jobs="QID50100",
                                  Type="Standard"))
    sesion.commit()
    podio([_item(100)])

    resumen, _ = _medir(sesion)

    assert resumen["jobs_afectados_con_comision_emitida"] == ["QID50100"]


# ------------------------------------------------------------ la paginación

def test_recorre_todas_las_paginas(sesion, podio):
    for ref in range(100, 105):
        _sembrar(sesion, ref, f"QID5{ref}")
    servicio = podio([_item(r) for r in range(100, 105)], tope_pagina=2)

    resumen, siguiente = _medir(sesion)

    assert siguiente is None, "se dejó páginas sin pedir"
    assert resumen["revisados"] == 5, "se dejó jobs sin revisar y no lo dijo"
    assert resumen["orders_a_vaciar"] == 5
    assert servicio.paginas_pedidas >= 3


def test_el_presupuesto_agotado_devuelve_offset_para_reencadenar(sesion, podio):
    for ref in range(100, 105):
        _sembrar(sesion, ref, f"QID5{ref}")
    podio([_item(r) for r in range(100, 105)], tope_pagina=1)

    resumen, siguiente = _medir(sesion, presupuesto=0)

    assert siguiente is not None, "se agotó el presupuesto y lo dio por completo"
    assert resumen["revisados"] < 5


def test_los_contadores_no_se_acotan_aunque_el_detalle_si(sesion, podio, monkeypatch):
    """Un tope silencioso en los CONTADORES se leería como «esto es todo»."""
    monkeypatch.setattr(Paridad, "TOPE_DETALLE_ORDENES", 2)
    for ref in range(100, 106):
        _sembrar(sesion, ref, f"QID5{ref}")
    podio([_item(r) for r in range(100, 106)])

    resumen, _ = _medir(sesion)

    assert resumen["orders_a_vaciar"] == 6, "acotó el contador, no solo el detalle"
    assert len(resumen["detalle"]) == 2
    assert resumen["jobs_omitidos_del_detalle"] == 4


# ---------------------------------------------------- lo que NO puede mentir
#
# Regla 5 del proyecto: ningún resultado parcial se presenta como completo. En
# este proyecto la ausencia de señal se ha leído como señal buena más de una vez,
# y esta ruta produce la cifra con la que se decide encender `PODIO_VACIA_SLOTS`
# sobre ~9.300 órdenes. Estos tests cubren las tres formas de mentir que tenía.

def test_un_item_repetido_entre_paginas_no_se_cuenta_dos_veces(sesion, podio):
    """Podio pagina por offset sobre una app VIVA: un job editado entre dos
    páginas puede reaparecer en la siguiente. Sin deduplicar, su Order se contaba
    dos veces en `orders_a_vaciar` mientras `jobs_afectados` la contaba una."""
    _sembrar(sesion, 100, "QID50100")
    podio([_item(100), _item(100)])  # el mismo ítem sale dos veces

    resumen, _ = _medir(sesion)

    assert resumen["items_repetidos_entre_paginas"] == 1
    assert resumen["orders_a_vaciar"] == 1, "contó dos veces la misma Order"
    assert resumen["formula_que_se_vacia"] == 500.0
    assert resumen["jobs_afectados"] == 1


def test_el_desglose_por_slot_cuadra_con_el_titular(sesion, podio):
    """Si `por_slot` contara también las saltadas, el desglose prometería
    vaciados que la guarda no va a hacer y no sumaría `orders_a_vaciar`."""
    _sembrar(sesion, 100, "QID50100")
    _sembrar(sesion, 101, "QID50101", Title="PO-QID50101-01")  # la salta la guarda
    podio([_item(100), _item(101)])

    resumen, _ = _medir(sesion)

    assert resumen["orders_a_vaciar"] == 1
    assert resumen["orders_saltadas_por_datos_locales"] == 1
    assert sum(resumen["por_slot"].values()) == resumen["orders_a_vaciar"]


# ------------------------------------------------- la vista y su `completo`

def _pedir(sesion, monkeypatch, consulta):
    """Llama a la vista con un contexto de petición mínimo, sin JWT ni Neon."""
    from contextlib import contextmanager

    from flask import Flask

    @contextmanager
    def _sesion_falsa():
        yield sesion

    monkeypatch.setattr(Paridad, "get_session", _sesion_falsa)
    with Flask(__name__).test_request_context(
            f"/admin/podio/obsoletos_ordenes?{consulta}"):
        respuesta, codigo = Paridad.obsoletos_ordenes()
        return respuesta.get_json(), codigo


def test_la_primera_llamada_que_ve_la_app_entera_si_es_completa(
        sesion, podio, monkeypatch):
    _sembrar(sesion, 100, "QID50100")
    podio([_item(100)])

    cuerpo, codigo = _pedir(sesion, monkeypatch, "type=QID&year=2025")

    assert codigo == 200
    assert cuerpo["completo"] is True
    assert "parcial" not in cuerpo and "inconsistente" not in cuerpo
    assert cuerpo["orders_a_vaciar"] == 1


def test_el_tramo_final_de_una_enumeracion_troceada_no_es_completo(
        sesion, podio, monkeypatch):
    """`siguiente is None` solo dice que ESTA llamada llegó al final de la app,
    no que haya visto la app entera. Marcarlo completo hacía que la ÚLTIMA
    respuesta —la única sin aviso— fuese justo la que más subestima."""
    for ref in range(100, 104):
        _sembrar(sesion, ref, f"QID5{ref}")
    podio([_item(r) for r in range(100, 104)])

    cuerpo, _ = _pedir(sesion, monkeypatch, "type=QID&year=2025&offset=2")

    assert cuerpo["completo"] is False, "presentó un tramo como la medida entera"
    assert "offset=2" in cuerpo["parcial"]


def test_si_la_app_se_movio_a_mitad_del_recuento_no_es_completo(
        sesion, podio, monkeypatch):
    """La sonda y la enumeración tienen que coincidir; si no, las cifras no
    describen un estado que haya existido."""
    _sembrar(sesion, 100, "QID50100")
    servicio = _ServicioPodio([_item(100)], 500)
    servicio.get_items_page = lambda limit=None, offset=0: (
        {"filtered": 7, "items": [_item(100)]} if limit == 1
        else {"items": [_item(100)] if offset == 0 else []})
    monkeypatch.setattr(Paridad.podio_jobs_router, "get_readonly_service",
                        lambda t, a: servicio)
    monkeypatch.setattr(Paridad, "TOPE_PAGINA", 500)

    cuerpo, _ = _pedir(sesion, monkeypatch, "type=QID&year=2025")

    assert cuerpo["completo"] is False
    assert "se movió mientras se contaba" in cuerpo["inconsistente"]
