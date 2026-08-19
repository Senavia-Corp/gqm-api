"""Integración (REG-016): webhook simulado → Neon develop.

POST directo al endpoint local con el payload dentro de `data["item"]`
(sin Podio en vivo). Verifica que sync_bdf / sync_purchases /
sync_ptl_gc_fee escriben BDF, materiales/rent y PTL-GC-fee correctos.
Develop es desechable, pero cada test limpia lo suyo.
"""
import uuid

import pytest
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.ChangeOrderModel import ChangeOrder
from src.models.EstimateCostModel import EstimateCost
from src.models.JobModel import Job
from src.models.OrderModel import Order
from src.models.PurchaseModel import Purchase

from tests.fixtures.podio_items import calc, money, ptl_item, qid_item


def _unique_ids(prefix):
    suffix = uuid.uuid4().int % 90000 + 10000
    return 900000000 + suffix, f"{prefix}9{suffix}"


def _cleanup(tracking_id, podio_item_id):
    with get_session() as session:
        for model, col, key in (
            (ChangeOrder, ChangeOrder.job_podio_id, str(podio_item_id)),
            (Order, Order.job_podio_id, str(podio_item_id)),
            (Purchase, Purchase.ID_Jobs, tracking_id),
        ):
            for row in session.exec(select(model).where(col == key)).all():
                session.delete(row)
        job = session.exec(select(Job).where(Job.ID_Jobs == tracking_id)).first()
        if job:
            session.delete(job)  # cascadea estimate_costs, tlactivity, tasks…
        session.commit()


def _post(client, app_type, year, item, event="item.create"):
    from decouple import config

    token = config("PODIO_WEBHOOK_TOKEN", default="")
    return client.post(
        f"/webhook/podio/jobs/{app_type}/{year}?token={token}",
        json={"type": event, "item_id": item["item_id"], "item": item},
    )


@pytest.fixture()
def qid_ids():
    item_id, tracking = _unique_ids("QID")
    yield item_id, tracking
    _cleanup(tracking, item_id)


@pytest.fixture()
def ptl_ids():
    item_id, tracking = _unique_ids("PTL")
    yield item_id, tracking
    _cleanup(tracking, item_id)


def test_qid_webhook_creates_job_and_bdf(client, qid_ids):
    item_id, tracking = qid_ids
    resp = _post(client, "QID", 2026, qid_item(item_id=item_id, tracking_id=tracking))
    assert resp.status_code == 200

    with get_session() as session:
        job = session.exec(select(Job).where(Job.ID_Jobs == tracking)).first()
        assert job is not None
        assert job.Job_type == "QID"
        assert job.Job_status == "In Progress"
        assert job.Project_name == "Vista Lagos Ph 2"
        assert job.podio_app_year == 2026  # REG-015: año de app persistido
        # Los agregados (Estimated_material/rent, Gqm_*) los reescribe
        # recalculate_and_apply desde los EstimateCost locales — el mapeo
        # crudo ya está congelado en tests/unit. Bldg_dept_fees sí es
        # estable: el recálculo lo deriva de las filas BDF que creó el sync.
        assert job.Bldg_dept_fees == [100.00, 150.00, 250.00]

        bdf = session.exec(
            select(EstimateCost)
            .where(EstimateCost.ID_Jobs == tracking, EstimateCost.Cost_type == "BDF")
            .order_by(EstimateCost.ID_EstimateCost)
        ).all()
        assert [c.Client_price for c in bdf] == [100.00, 150.00, 250.00]
        assert all(c.Status == "Approved" for c in bdf)


def _bdf(tracking):
    with get_session() as session:
        return session.exec(
            select(EstimateCost)
            .where(EstimateCost.ID_Jobs == tracking, EstimateCost.Cost_type == "BDF")
            .order_by(EstimateCost.ID_EstimateCost)
        ).all()


def test_qid_webhook_bdf_edita_el_importe_y_no_borra_lo_ausente(client, qid_ids):
    """DECISION DEL CLIENTE (Sebastian, 18-ago-2026): «si en Podio se elimina,
    no hace nada». Antes este test fijaba lo contrario — quitar el hueco 3
    BORRABA el coste — que es el defecto G5.

    Editar SI se aplica; la ausencia NO.
    """
    item_id, tracking = qid_ids
    assert _post(client, "QID", 2026, qid_item(item_id=item_id, tracking_id=tracking)).status_code == 200

    updated = qid_item(item_id=item_id, tracking_id=tracking)
    updated["fields"] = [f for f in updated["fields"]
                         if f["external_id"] != "bldg-dept-fees-3"]
    for f in updated["fields"]:
        if f["external_id"] == "bldg-fees-1":
            f["values"] = [{"value": "175.00"}]
    assert _post(client, "QID", 2026, updated, event="item.update").status_code == 200

    bdf = _bdf(tracking)
    assert [c.Client_price for c in bdf] == [175.00, 150.00, 250.00], (
        "el hueco ausente no debe borrar su coste")
    assert [c.podio_field for c in bdf] == [
        "bldg-fees-1", "bldg-fees-2", "bldg-dept-fees-3"]


def test_qid_webhook_un_hueco_intermedio_vacio_no_desplaza_a_los_siguientes(client, qid_ids):
    """El desplazamiento silencioso que motivo el cambio de fuente.

    El lector `multi` solo acumulaba los campos presentes, asi que con
    `bldg-fees-2` vacio producia `[100, 250]` y el 250 acababa escrito en la
    fila del hueco 2. El test viejo no lo veia porque vaciaba el ULTIMO hueco,
    el unico caso donde el desplazamiento no se nota.
    """
    item_id, tracking = qid_ids
    assert _post(client, "QID", 2026, qid_item(item_id=item_id, tracking_id=tracking)).status_code == 200

    updated = qid_item(item_id=item_id, tracking_id=tracking)
    for f in updated["fields"]:
        if f["external_id"] == "bldg-fees-2":
            f["values"] = []          # presente pero VACIO
    assert _post(client, "QID", 2026, updated, event="item.update").status_code == 200

    por_hueco = {c.podio_field: c.Client_price for c in _bdf(tracking)}
    assert por_hueco["bldg-fees-1"] == 100.00
    assert por_hueco["bldg-dept-fees-3"] == 250.00, "el 250 no puede caer en el hueco 2"
    assert por_hueco["bldg-fees-2"] == 150.00, "vaciar en Podio no toca el importe"


def test_qid_webhook_syncs_rent_and_purchases(client, qid_ids):
    item_id, tracking = qid_ids
    assert _post(client, "QID", 2026, qid_item(item_id=item_id, tracking_id=tracking)).status_code == 200

    with get_session() as session:
        session.add(EstimateCost(
            ID_EstimateCost=f"ESTT{item_id % 100000}",
            ID_Jobs=tracking, Cost_type="Rent", Status="Approved",
            Title="Rent test", Client_price=0.0,
        ))
        session.add(Purchase(
            ID_Purchase=f"PURT{item_id % 100000}",
            ID_Jobs=tracking, Total_spending=0.0,
        ))
        session.commit()

    updated = qid_item(item_id=item_id, tracking_id=tracking)
    updated["fields"] += [
        money("materials-purchased-1-2", "111.11"),
        calc("materials-purchased-2", "222.22"),
    ]
    assert _post(client, "QID", 2026, updated, event="item.update").status_code == 200

    with get_session() as session:
        rent = session.exec(select(EstimateCost).where(
            EstimateCost.ID_Jobs == tracking, EstimateCost.Cost_type == "Rent")).first()
        purchase = session.exec(select(Purchase).where(Purchase.ID_Jobs == tracking)).first()
        assert rent.Client_price == 111.11   # slot 1 → Rent
        assert purchase.Total_spending == 222.22  # slot 2 → Purchase


@pytest.fixture()
def par_ids():
    item_id, tracking = _unique_ids("PAR")
    yield item_id, tracking
    _cleanup(tracking, item_id)


def test_par_webhook_syncs_order_with_payments(client, par_ids):
    """REG-001: Formula = total del tech; check-amount-payment-N = cuotas."""
    from tests.fixtures.podio_items import par_item

    item_id, tracking = par_ids
    item = par_item(item_id=item_id, tracking_id=tracking)
    item["fields"] += [
        calc("tech-1-ptl-original-pricing", "1000.00"),
        money("check-amount-payment-1", "300.00"),
        money("check-amount-payment-2", "200.00"),
    ]
    assert _post(client, "PAR", 2026, item).status_code == 200

    with get_session() as session:
        order = session.exec(select(Order).where(
            Order.job_podio_id == str(item_id))).first()
        assert order is not None
        assert order.Formula == 1000.00
        assert (order.Payment_1, order.Payment_2, order.Payment_3) == (300.00, 200.00, None)

    # Las cuotas viven ahora en `order_payment`, con su hueco declarado.
    from src.models.OrderPaymentModel import OrderPayment
    with get_session() as session:
        cuotas = session.exec(select(OrderPayment).where(
            OrderPayment.job_podio_id == str(item_id))
            .order_by(OrderPayment.Installment)).all()
        assert [(c.Installment, c.Amount, c.podio_field) for c in cuotas] == [
            (1, 300.00, "check-amount-payment-1"),
            (2, 200.00, "check-amount-payment-2"),
        ]

    # DECISION DEL CLIENTE (18-ago-2026): vaciar el cheque 2 en Podio NO borra
    # nada. Antes este test fijaba lo contrario — el slot se limpiaba — que es
    # el defecto G5 en su cuarto sitio.
    updated = par_item(item_id=item_id, tracking_id=tracking)
    updated["fields"] += [
        calc("tech-1-ptl-original-pricing", "1000.00"),
        money("check-amount-payment-1", "300.00"),
    ]
    assert _post(client, "PAR", 2026, updated, event="item.update").status_code == 200

    with get_session() as session:
        order = session.exec(select(Order).where(
            Order.job_podio_id == str(item_id))).first()
        assert (order.Payment_1, order.Payment_2) == (300.00, 200.00), (
            "vaciar en Podio no borra el importe que ya estaba")
        cuotas = session.exec(select(OrderPayment).where(
            OrderPayment.job_podio_id == str(item_id))).all()
        assert len(cuotas) == 2, "tampoco se borra la fila de la cuota"


def test_podio_readonly_no_mata_el_sync_entrante(client, qid_ids, monkeypatch):
    """`PODIO_READONLY` corta lo SALIENTE; lo entrante tiene que seguir entrando.

    Durante la ventana de reconciliación la bandera está encendida para que ni
    una importación ni un `PATCH ?sync_podio=true` toquen las apps. Si además
    matara las entregas de webhook, el sync moriría justo mientras se comparan
    contadores y la divergencia crecería en vez de cerrarse.

    Esta es la invariante que hace que la bandera sea usable en producción.
    """
    from src.podio.services import podio_base_services as pbs

    monkeypatch.setattr(pbs, "PODIO_READONLY", True)

    item_id, tracking = qid_ids
    resp = _post(client, "QID", 2026, qid_item(item_id=item_id, tracking_id=tracking))
    assert resp.status_code == 200

    with get_session() as session:
        job = session.exec(select(Job).where(Job.ID_Jobs == tracking)).first()
        assert job is not None, (
            "PODIO_READONLY bloqueó una escritura ENTRANTE: el webhook no guardó el job"
        )
        assert job.podio_app_year == 2026


def test_ptl_webhook_creates_gc_fee(client, ptl_ids):
    item_id, tracking = ptl_ids
    resp = _post(client, "PTL", 2026, ptl_item(item_id=item_id, tracking_id=tracking))
    assert resp.status_code == 200

    with get_session() as session:
        job = session.exec(select(Job).where(Job.ID_Jobs == tracking)).first()
        assert job is not None and job.Ptl_gc_fee == 800.00

        gcf = session.exec(select(EstimateCost).where(
            EstimateCost.ID_Jobs == tracking, EstimateCost.Cost_type == "PTLGCF")).all()
        assert len(gcf) == 1
        assert gcf[0].Client_price == 800.00 and gcf[0].Builder_cost == 800.00
