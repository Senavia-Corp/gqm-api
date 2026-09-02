"""No-regresión (1-sep-2026): quitar un técnico en Podio TIENE que vaciar su fila.

Gemelo en FILAS del arreglo en columnas de `test_mapper_vacia_campos_borrados.py`.
Podio omite del item los campos vacíos y `item_de_confianza` relee siempre el
item entero, así que un slot ausente significa «ese técnico ya no está».

Los dos lectores (`jobs_hook_sync` y `sync_orders`) construían `tech_data` solo
con los campos presentes: el vaciado PARCIAL ya funcionaba —`upsert_order`
recibe None y lo escribe—, pero un slot que desaparecía ENTERO no se visitaba
nunca y la fila conservaba su dinero indefinidamente.

La otra mitad del contrato: **ausente no siempre es vaciado**. Si la fila la
construyó una persona (un PO del panel), si la columna la gobierna el recálculo
local, o si la cuota no existe en esa app-año (REG-073), escribir NULL sería
destruir un dato bueno.

Se usa SQLite en memoria con las tablas justas —no un doble de sesión— para que
el SELECT por `(job_podio_id, tech_field)` que decide todo se ejecute de verdad.
"""
import pytest
from sqlmodel import SQLModel, Session, create_engine, select

import src.models  # noqa: F401  (puebla el metadata)
import src.podio.sync.sync_orders as so
from src.models.ChangeOrderModel import ChangeOrder
from src.models.EstimateCostModel import EstimateCost
from src.models.FinancialDocModel import FinancialDocument
from src.models.OpportunitiesModel import Opportunities
from src.models.OrderModel import Order
from tests.fixtures.podio_items import app_ref, calc, item, money, text

# La real, capturada antes de que el fixture autouse la sustituya: los dos
# tests del final prueban ESTA funcion, no el doble.
_CAMPOS_DE_LA_APP_REAL = so.campos_de_la_app

ITEM = "990500"
TABLAS = ("order", "change_order", "estimate_cost", "financial_document",
          "opportunities")


@pytest.fixture()
def sesion():
    motor = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        motor, tables=[SQLModel.metadata.tables[t] for t in TABLAS])
    with Session(motor) as s:
        yield s


@pytest.fixture(autouse=True)
def flag_encendido(monkeypatch):
    monkeypatch.setenv("PODIO_VACIA_SLOTS", "true")


@pytest.fixture(autouse=True)
def esquema_de_la_app(monkeypatch):
    """`campos_de_la_app` sale a Podio a leer el esquema. En unitarios se
    sustituye por uno que lo tiene todo, para que cada test hable de lo que dice
    su nombre y no de la red. El comportamiento del esquema tiene sus propios
    tests, abajo."""
    todo = frozenset(
        [s for m in (so.TECH_FORMULA_FIELDS, so.TECH_ADJ_FORMULA_FIELDS,
                     so.TECH_HD_MATERIALS_FIELDS, so.TECH_NOTES_FIELDS,
                     so.TECH_PAYMENT_FIELDS, so.ORDER_CHANGE_ORDERS_FIELDS)
         for por_tipo in (m.values() if "QID" in m else [m])
         for slugs in (por_tipo.values() if isinstance(por_tipo, dict) else [])
         for s in slugs] + list(so.TECHNICIAN_FIELDS.values())[0])
    monkeypatch.setattr(so, "campos_de_la_app", lambda t, a: todo)
    return todo


def _orden(sesion, tech_field, **kw):
    campos = {"Formula": 500.0, "Adj_formula": 500.0, "Notes": "nota vieja",
              "Ptl_hd_materials": 42.0, "ID_Subcontractor": None}
    campos.update(kw)
    fila = Order(ID_Order=kw.pop("ID_Order", "ORD-TEST"), job_podio_id=ITEM,
                 tech_field=tech_field, **campos)
    sesion.add(fila)
    sesion.commit()
    return fila


def _co(sesion, podio_field, formula=250.0, id_order="ORD-TEST"):
    fila = ChangeOrder(ID_ChangeOrder="ChO-TEST", job_podio_id=ITEM,
                       podio_field=podio_field, ChangeOrderFormula=formula,
                       ID_Order=id_order)
    sesion.add(fila)
    sesion.commit()
    return fila


def _vaciar(sesion, vistos=(), tipo="QID", anio=2025, **kw):
    return so.vaciar_slots_ausentes(sesion, ITEM, tipo, anio, set(vistos), **kw)


# ------------------------------------------------------------------ vaciar

def test_slot_entero_ausente_vacia_la_fila(sesion):
    """El caso que faltaba: el técnico se quitó de Podio y nadie visitaba su fila."""
    orden = _orden(sesion, "labor-tech-5")

    informe = _vaciar(sesion, vistos={1})

    assert [f["ID_Order"] for f in informe] == ["ORD-TEST"]
    assert orden.Formula is None
    assert orden.Notes is None
    assert orden.Ptl_hd_materials is None


def test_un_change_order_ausente_se_vacia(sesion):
    co = _co(sesion, "tech-1-change-order-2")

    informe = so.vaciar_cos_ausentes(sesion, ITEM, "QID", presentes=set())

    assert [f["ID_ChangeOrder"] for f in informe] == ["ChO-TEST"]
    assert co.ChangeOrderFormula is None
    assert co.ID_Order == "ORD-TEST", "reparentar lo colaría en Gqm_total_change_orders"


def test_el_slot_que_si_viene_no_se_toca(sesion):
    orden = _orden(sesion, "labor-tech-5")

    _vaciar(sesion, vistos={5})

    assert orden.Formula == 500.0


# ---------------------------------------------------------------- NO vaciar

def test_adj_formula_nunca_se_vacia(sesion):
    """La reescribe siempre `recalculate_order_formulas`: vaciarla es churn."""
    orden = _orden(sesion, "labor-tech-5")

    _vaciar(sesion)

    assert orden.Adj_formula == 500.0


def test_id_subcontractor_no_se_toca_en_esta_fase(sesion):
    """Desvincular saca la orden del portal de ese subcontratista (REG-110)."""
    orden = _orden(sesion, "labor-tech-5", ID_Subcontractor="SUBC1")

    _vaciar(sesion)

    assert orden.ID_Subcontractor == "SUBC1"


@pytest.mark.parametrize("cuelga", ["Title", "estimate_cost",
                                    "financial_document", "opportunity"])
def test_una_order_con_datos_locales_no_se_vacia(sesion, caplog, cuelga):
    """`upsert_order` no escribe `Title` ni cuelga costes, facturas ni
    oportunidades: si algo de eso está ahí la fila la hizo una persona, y su
    slot puede no existir en Podio (`POST /order/?sync_podio=false`)."""
    orden = _orden(sesion, "labor-tech-5",
                   Title="PO-QID6466-0001" if cuelga == "Title" else None)
    if cuelga == "estimate_cost":
        sesion.add(EstimateCost(ID_EstimateCost="EST1", ID_Order=orden.ID_Order))
    elif cuelga == "financial_document":
        sesion.add(FinancialDocument(ID_FinancialDoc="FD1", Type_of_document="Bill",
                                    ID_Order=orden.ID_Order))
    elif cuelga == "opportunity":
        sesion.add(Opportunities(ID_Opportunities="OPP1", ID_Order=orden.ID_Order))
    sesion.commit()

    import logging
    with caplog.at_level(logging.WARNING):
        informe = _vaciar(sesion)

    assert orden.Formula == 500.0, "destruyó un importe que Podio nunca gobernó"
    assert informe and informe[0]["saltada"] is True
    assert "NO se vacia" in caplog.text, "la divergencia se resolvió en silencio"
    assert orden.ID_Order in caplog.text


def test_una_order_en_slot_de_change_order_no_se_encuentra(sesion):
    """`tech_field` puede ser un slug de CO (`resolve_tech_index_from_field`).
    La búsqueda va por los slugs de FÓRMULA, así que esa fila queda fuera."""
    orden = _orden(sesion, "tech-1-change-order-2")

    assert _vaciar(sesion) == []
    assert orden.Formula == 500.0


def test_par_2023_no_vacia_las_cuotas_que_esa_app_no_tiene(sesion):
    """REG-073: PAR 2023 no tiene `tech-3-payment-*`, así que su ausencia no
    dice que estén vacías."""
    orden = _orden(sesion, "tech-3-formula", Payment_1=100.0, Payment_2=200.0)

    _vaciar(sesion, tipo="PAR", anio=2023)

    assert orden.Formula is None, "la fórmula sí se vacía"
    assert (orden.Payment_1, orden.Payment_2) == (100.0, 200.0)


def test_pero_en_una_app_anio_que_si_las_tiene_se_vacian(sesion):
    orden = _orden(sesion, "tech-3-formula", Payment_1=100.0, Payment_2=200.0)

    _vaciar(sesion, tipo="PAR", anio=2025)

    assert orden.Payment_1 is None and orden.Payment_2 is None


def test_sin_anio_de_app_no_se_vacia_nada(sesion):
    """Jobs sembrados por tests (`QID80001`) y cualquier ID que la regla del año
    no reconozca: sin año no hay tabla de huecos que consultar."""
    orden = _orden(sesion, "labor-tech-5")

    assert _vaciar(sesion, anio=None) == []
    assert orden.Formula == 500.0


def test_con_el_flag_apagado_no_se_escribe_nada(sesion, monkeypatch):
    """El despliegue no puede ser el mismo acto que mover los agregados."""
    monkeypatch.setenv("PODIO_VACIA_SLOTS", "false")
    orden = _orden(sesion, "labor-tech-5")
    co = _co(sesion, "tech-1-change-order-2")

    assert _vaciar(sesion) == []
    assert so.vaciar_cos_ausentes(sesion, ITEM, "QID", presentes=set()) == []
    assert orden.Formula == 500.0 and co.ChangeOrderFormula == 250.0


def test_el_dry_run_mide_aunque_el_flag_este_apagado(sesion, monkeypatch):
    """La medida existe justo para decidir si encender el flag."""
    monkeypatch.setenv("PODIO_VACIA_SLOTS", "false")
    orden = _orden(sesion, "labor-tech-5")

    informe = _vaciar(sesion, dry_run=True)

    assert informe and informe[0]["antes"]["Formula"] == 500.0
    assert informe[0]["adj_formula"] == 500.0
    assert orden.Formula == 500.0, "un dry_run no puede escribir"


def test_los_change_orders_de_nivel_proyecto_no_se_tocan(sesion):
    """Mueven `Acc_receivable` (ingresos) y van en otra fase."""
    co = _co(sesion, "change-order-1", id_order=None)

    assert so.vaciar_cos_ausentes(sesion, ITEM, "QID", presentes=set()) == []
    assert co.ChangeOrderFormula == 250.0


# --------------------------------------------------------------- invariantes

def test_una_segunda_pasada_no_escribe_nada(sesion):
    """Idempotencia: si no, cada entrega movería `updated_at` de media base."""
    _orden(sesion, "labor-tech-5")

    assert _vaciar(sesion) != []
    assert _vaciar(sesion) == []


def test_nunca_se_borra_una_fila_ni_cambia_su_identidad(sesion):
    _orden(sesion, "labor-tech-5")

    _vaciar(sesion)
    sesion.commit()

    fila = sesion.exec(select(Order)).one()
    assert (fila.ID_Order, fila.job_podio_id, fila.tech_field) == (
        "ORD-TEST", ITEM, "labor-tech-5")


# ------------------------------------------- el predicado de "el slot sigue"

def test_un_technician_sin_subcontractor_en_la_bd_cuenta_como_presente():
    """`tech_data` no recibe ese índice porque `extract_subcontractor_from_field`
    devuelve None, y tomar eso por «el slot ya no está» vaciaría una Order que
    Podio sigue teniendo. Por eso el predicado mira el PAYLOAD."""
    vistos, _ = so.slots_y_cos_presentes(
        [app_ref("technician-2", 111)], "QID")

    assert vistos == {1}


def test_cualquier_campo_del_slot_prueba_que_el_tecnico_sigue():
    campos = [calc("tech-5-adj-formula", "10"), text("tech-2-description", "x"),
              money("tech-3-payment-1", "50")]
    vistos_qid, _ = so.slots_y_cos_presentes(campos, "QID")
    vistos_par, _ = so.slots_y_cos_presentes(campos, "PAR")

    assert 5 in vistos_qid          # adj
    assert {2, 3} <= vistos_par     # notas y cuota


def test_un_campo_presente_pero_vacio_no_cuenta_como_presente():
    """Podio suele omitir el campo, pero también puede mandarlo con `values: []`."""
    vacio = {"external_id": "labor-tech-5", "type": "money", "values": []}

    vistos, _ = so.slots_y_cos_presentes([vacio], "QID")

    assert vistos == set()


def test_los_cos_presentes_solo_cuentan_los_de_nivel_orden():
    _, cos = so.slots_y_cos_presentes(
        [calc("tech-1-change-order-2", "1"), calc("change-order-1", "2")], "QID")

    assert cos == {"tech-1-change-order-2"}


def test_el_item_canonico_no_deja_ningun_slot_vivo_por_error():
    """Red de seguridad: un item sin campos de técnico no puede dar `vistos`."""
    limpio = item(990500, "QID60500", [text("project-location", "x")])

    vistos, cos = so.slots_y_cos_presentes(limpio["fields"], "QID")

    assert (vistos, cos) == (set(), set())


# ------------------------------------------------- el índice de la medida

def test_el_catalogo_da_exactamente_lo_mismo_que_las_consultas(sesion):
    """Dos backends de búsqueda para un solo predicado: si divergen, la medida
    deja de decir nada sobre lo que el arreglo hace."""
    _orden(sesion, "labor-tech-5")
    _co(sesion, "tech-1-change-order-2")
    catalogo = so.catalogo_de_slots(sesion, [ITEM])

    por_consulta = (_vaciar(sesion, dry_run=True),
                    so.vaciar_cos_ausentes(sesion, ITEM, "QID", set(),
                                           dry_run=True))
    por_catalogo = (_vaciar(sesion, dry_run=True, catalogo=catalogo),
                    so.vaciar_cos_ausentes(sesion, ITEM, "QID", set(),
                                           dry_run=True, catalogo=catalogo))

    assert por_consulta == por_catalogo


def test_el_catalogo_no_indexa_los_cos_de_nivel_proyecto(sesion):
    _co(sesion, "change-order-1", id_order=None)

    catalogo = so.catalogo_de_slots(sesion, [ITEM])

    assert catalogo["change_orders"] == {}


def test_un_catalogo_vacio_no_consulta_nada(sesion):
    assert so.catalogo_de_slots(sesion, []) == {"orders": {},
                                                "change_orders": {}}


# ------------------------------------------------ el cableado de los lectores
#
# Los tests de arriba prueban los helpers sueltos. Estos prueban que los DOS
# lectores los llaman de verdad: un helper correcto que nadie invoca no arregla
# nada, y el cableado es donde se decide `vistos` y el año de la app.

@pytest.fixture()
def sesion_con_jobs():
    tablas = TABLAS + ("jobs", "subcontractor")
    motor = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        motor, tables=[SQLModel.metadata.tables[t] for t in tablas])
    with Session(motor) as s:
        yield s


def _mundo(sesion, id_jobs="QID50500", tech_field="labor-tech-5"):
    from src.models.JobModel import Job

    job = Job(ID_Jobs=id_jobs, podio_item_id=ITEM, Job_type="QID")
    sesion.add(job)
    sesion.add(Order(ID_Order="ORD-TEST", job_podio_id=ITEM,
                     tech_field=tech_field, Formula=500.0, Adj_formula=500.0))
    sesion.commit()
    return job


def _item_podio(campos):
    return {"item_id": int(ITEM), "app_item_id_formatted": "QID50500",
            "fields": [{"external_id": e, "type": "money",
                        "values": [{"value": "1"}]} for e in campos]}


def test_el_webhook_vacia_el_slot_que_ya_no_viene(sesion_con_jobs):
    """`add_job_orders_and_change_orders` deriva el año de `resolver_anio_app`."""
    from src.podio.webhook.jobs_hook_sync import add_job_orders_and_change_orders

    job = _mundo(sesion_con_jobs)
    add_job_orders_and_change_orders(
        sesion_con_jobs, job, _item_podio(["tech-1-ptl-original-pricing"]), "QID")

    assert sesion_con_jobs.get(Order, "ORD-TEST").Formula is None


def test_el_webhook_no_vacia_el_slot_que_si_viene(sesion_con_jobs):
    """Con el slot presente manda Podio: `upsert_order` escribe SU valor. Lo que
    no puede pasar es que el vaciado se cuele y lo ponga a NULL."""
    from src.podio.webhook.jobs_hook_sync import add_job_orders_and_change_orders

    job = _mundo(sesion_con_jobs)
    add_job_orders_and_change_orders(
        sesion_con_jobs, job, _item_podio(["labor-tech-5"]), "QID")

    assert sesion_con_jobs.get(Order, "ORD-TEST").Formula == 1.0


def test_el_webhook_no_vacia_un_job_sin_anio_de_app(sesion_con_jobs):
    """`QID80001` y demás sembrados por tests: sin año, comportamiento conservador.
    Esto solo lo puede comprobar el cableado — el helper recibe el año ya resuelto."""
    from src.podio.webhook.jobs_hook_sync import add_job_orders_and_change_orders

    job = _mundo(sesion_con_jobs, id_jobs="QID80001")
    add_job_orders_and_change_orders(
        sesion_con_jobs, job, _item_podio(["tech-1-ptl-original-pricing"]), "QID")

    assert sesion_con_jobs.get(Order, "ORD-TEST").Formula == 500.0


def test_el_webhook_con_el_flag_apagado_no_toca_nada(sesion_con_jobs, monkeypatch):
    from src.podio.webhook.jobs_hook_sync import add_job_orders_and_change_orders

    monkeypatch.setenv("PODIO_VACIA_SLOTS", "false")
    job = _mundo(sesion_con_jobs)
    add_job_orders_and_change_orders(
        sesion_con_jobs, job, _item_podio(["tech-1-ptl-original-pricing"]), "QID")

    assert sesion_con_jobs.get(Order, "ORD-TEST").Formula == 500.0


def test_el_webhook_vacia_tambien_el_change_order_ausente(sesion_con_jobs):
    from src.podio.webhook.jobs_hook_sync import add_job_orders_and_change_orders

    job = _mundo(sesion_con_jobs, tech_field="tech-1-ptl-original-pricing")
    sesion_con_jobs.add(ChangeOrder(
        ID_ChangeOrder="ChO-TEST", job_podio_id=ITEM,
        podio_field="tech-1-change-order-2", ChangeOrderFormula=90.0,
        ID_Order="ORD-TEST"))
    sesion_con_jobs.commit()

    add_job_orders_and_change_orders(
        sesion_con_jobs, job, _item_podio(["tech-1-ptl-original-pricing"]), "QID")

    assert sesion_con_jobs.get(ChangeOrder, "ChO-TEST").ChangeOrderFormula is None


def test_el_log_del_dry_run_no_afirma_que_vacio(sesion, caplog):
    """La ruta de medida recorre miles de ítems en `dry_run`. Si el log dijera
    «se vacia» también ahí, dejaría miles de líneas afirmando que el cambio
    corrió — y en este proyecto eso ya se ha leído como señal buena."""
    import logging

    _orden(sesion, "labor-tech-5")
    with caplog.at_level(logging.INFO):
        _vaciar(sesion, dry_run=True)
        simulado = caplog.text
        caplog.clear()
        _vaciar(sesion)
        real = caplog.text

    assert "SE VACIARIA" in simulado and "se vacia " not in simulado
    assert "se vacia " in real and "SE VACIARIA" not in real


@pytest.mark.parametrize("tipo, tech_field", [
    ("QID", "labor-tech-5"),
    ("PTL", "tech-3-ptl-original-pricing"),
])
def test_las_cuotas_no_se_vacian_en_tipos_que_no_las_tienen(sesion, tipo, tech_field):
    """`TECH_PAYMENT_FIELDS` solo tiene PAR: en QID y PTL, Podio no tiene campo de
    cuota, así que un `Payment_N` con valor solo lo pudo escribir una persona por
    `POST`/`PATCH /order/` y no hay nada en Podio con lo que devolverlo. Es la
    misma regla que `upsert_order` ya documenta: `payments=None` = no tocar."""
    orden = _orden(sesion, tech_field, Payment_1=1500.0)

    _vaciar(sesion, tipo=tipo)

    assert orden.Formula is None, "la fórmula sí se vacía"
    assert orden.Payment_1 == 1500.0, "destruyó un cheque sin vuelta atrás"


# ------------------------------------ el esquema real de la app (Excepción 2)
#
# Un item de Podio solo trae los campos CON VALOR, así que de él no se puede
# distinguir «vacío en Podio» de «ese campo no existe en esta app-año». Y la
# diferencia mueve dinero: medido el 2026-09-02, la app de QID 2025 no tiene 11
# de los 49 slugs de change order declarados para QID, y en producción cuelgan 8
# change orders vivos de slugs así — uno de 18.000 USD en QID 2023.

def test_un_co_cuyo_slug_no_existe_en_esa_app_anio_no_se_vacia(sesion, monkeypatch):
    """El caso de los 18.000 USD: `tech-4-change-order-4` no está en todas las
    apps de QID. Su ausencia del item no dice que esté vacío."""
    co = _co(sesion, "tech-4-change-order-4", formula=18000.0)
    monkeypatch.setattr(so, "campos_de_la_app",
                        lambda t, a: frozenset({"tech-1-change-order-2"}))

    assert so.vaciar_cos_ausentes(sesion, ITEM, "QID", set(), 2023) == []
    assert co.ChangeOrderFormula == 18000.0


def test_un_slot_cuya_formula_no_existe_en_esa_app_anio_no_se_vacia(sesion, monkeypatch):
    orden = _orden(sesion, "labor-tech-5")
    monkeypatch.setattr(so, "campos_de_la_app",
                        lambda t, a: frozenset({"tech-1-ptl-original-pricing"}))

    assert _vaciar(sesion) == []
    assert orden.Formula == 500.0


@pytest.mark.parametrize("fn", ["slots", "cos"])
def test_si_no_se_puede_leer_el_esquema_no_se_vacia_nada(sesion, monkeypatch, fn):
    """Fallar CERRADO: `None` significa «no se sabe», y el coste de equivocarse
    en la otra dirección es destruir dinero que nadie puede devolver."""
    orden = _orden(sesion, "labor-tech-5")
    co = _co(sesion, "tech-1-change-order-2")
    monkeypatch.setattr(so, "campos_de_la_app", lambda t, a: None)

    if fn == "slots":
        assert _vaciar(sesion) == []
    else:
        assert so.vaciar_cos_ausentes(sesion, ITEM, "QID", set(), 2025) == []
    assert orden.Formula == 500.0 and co.ChangeOrderFormula == 250.0


def test_el_esquema_ilegible_se_registra_y_no_revienta(monkeypatch, caplog):
    """Un fallo de Podio no puede tumbar el webhook, pero tampoco puede pasar
    desapercibido: si no se avisa, «no se vació nada» se lee como «no había nada»."""
    import logging

    class _Explota:
        def get_app_fields(self):
            raise RuntimeError("Podio no contesta")

    monkeypatch.setattr(so.podio_jobs_router, "get_readonly_service",
                        lambda t, a: _Explota())
    monkeypatch.setattr(so, "_ESQUEMA_APP", {})

    with caplog.at_level(logging.ERROR):
        assert _CAMPOS_DE_LA_APP_REAL("QID", 2025) is None
    assert "no se pudo leer el esquema" in caplog.text


def test_el_esquema_se_cachea_y_no_se_pide_dos_veces(monkeypatch):
    """Sin caché, cada `item.update` añadiría una llamada a Podio."""
    llamadas = []

    class _Servicio:
        def get_app_fields(self):
            llamadas.append(1)
            return {"labor-tech-5"}

    monkeypatch.setattr(so.podio_jobs_router, "get_readonly_service",
                        lambda t, a: _Servicio())
    monkeypatch.setattr(so, "_ESQUEMA_APP", {})

    _CAMPOS_DE_LA_APP_REAL("QID", 2025)
    _CAMPOS_DE_LA_APP_REAL("QID", 2025)
    _CAMPOS_DE_LA_APP_REAL("QID", 2026)

    assert len(llamadas) == 2, "no cacheó por app-año"
