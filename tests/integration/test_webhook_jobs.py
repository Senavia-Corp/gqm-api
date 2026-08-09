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
    return client.post(
        f"/webhook/podio/jobs/{app_type}/{year}",
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


def test_qid_webhook_update_bdf_edits_and_prunes(client, qid_ids):
    item_id, tracking = qid_ids
    assert _post(client, "QID", 2026, qid_item(item_id=item_id, tracking_id=tracking)).status_code == 200

    # Podio edita el fee 1 y borra el tercero
    updated = qid_item(item_id=item_id, tracking_id=tracking)
    updated["fields"] = [
        f for f in updated["fields"] if f["external_id"] != "bldg-dept-fees-3"
    ]
    for f in updated["fields"]:
        if f["external_id"] == "bldg-fees-1":
            f["values"] = [{"value": "175.00"}]
    assert _post(client, "QID", 2026, updated, event="item.update").status_code == 200

    with get_session() as session:
        bdf = session.exec(
            select(EstimateCost)
            .where(EstimateCost.ID_Jobs == tracking, EstimateCost.Cost_type == "BDF")
            .order_by(EstimateCost.ID_EstimateCost)
        ).all()
        assert [c.Client_price for c in bdf] == [175.00, 150.00]


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

    # Podio borra el cheque 2 → el slot se limpia (Podio es fuente de verdad)
    updated = par_item(item_id=item_id, tracking_id=tracking)
    updated["fields"] += [
        calc("tech-1-ptl-original-pricing", "1000.00"),
        money("check-amount-payment-1", "300.00"),
    ]
    assert _post(client, "PAR", 2026, updated, event="item.update").status_code == 200

    with get_session() as session:
        order = session.exec(select(Order).where(
            Order.job_podio_id == str(item_id))).first()
        assert (order.Payment_1, order.Payment_2) == (300.00, None)


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
