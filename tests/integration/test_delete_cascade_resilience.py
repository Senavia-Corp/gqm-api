"""Resiliencia de la cascada de borrado (objetivo: sync Podio↔app sin errores).

Reproduce el failed_sync #12: item.delete desde Podio sobre un job con
change orders + links duplicados, y la carrera panel-vs-webhook.
"""
import uuid

import pytest
from decouple import config
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.ChangeOrderModel import ChangeOrder
from src.models.EstimateCostModel import EstimateCost
from src.models.FinancialDocModel import FinancialDocument
from src.models.JobModel import Job
from src.models.MemberModel import Member
from src.models.OrderModel import Order
from src.models.link_models.JobMember import JobMemberLink


@pytest.fixture()
def world():
    """Job con toda la parentela: order, CO por las 3 vías, findoc, links."""
    sfx = uuid.uuid4().int % 90000 + 10000
    item_id = 920000000 + sfx
    ids = {
        "item": item_id,
        "job": f"QIDR{sfx}",
        "order": f"ORDR{sfx}",
        "co_ref": f"CHR1{sfx}",    # por job_podio_id
        "co_order": f"CHR2{sfx}",  # solo por ID_Order
        "co_job": f"CHR3{sfx}",    # solo por ID_Jobs
        "fdoc": f"FDR{sfx}",
        "est": f"ESTR{sfx}",
        "survivor": f"QIDS{sfx}",
    }
    with get_session() as s:
        s.add(Job(ID_Jobs=ids["job"], Job_type="QID", podio_item_id=str(item_id)))
        s.add(Job(ID_Jobs=ids["survivor"], Job_type="QID"))
        s.add(Order(ID_Order=ids["order"], job_podio_id=str(item_id), Formula=500.0))
        s.add(ChangeOrder(ID_ChangeOrder=ids["co_ref"], job_podio_id=str(item_id)))
        s.add(ChangeOrder(ID_ChangeOrder=ids["co_order"], ID_Order=ids["order"]))
        s.add(ChangeOrder(ID_ChangeOrder=ids["co_job"], ID_Jobs=ids["job"]))
        s.add(FinancialDocument(ID_FinancialDoc=ids["fdoc"], ID_Jobs=ids["job"],
                                Type_of_document="Bill"))
        s.add(EstimateCost(ID_EstimateCost=ids["est"], ID_Jobs=ids["survivor"],
                           ID_Order=ids["order"]))
        member = s.exec(select(Member)).first()
        if member:
            s.add(JobMemberLink(job_id=ids["job"], member_id=member.ID_Member,
                                rol="PM"))
        s.commit()
    yield ids
    with get_session() as s:
        for model, col, val in (
            (EstimateCost, EstimateCost.ID_EstimateCost, ids["est"]),
            (FinancialDocument, FinancialDocument.ID_FinancialDoc, ids["fdoc"]),
            (ChangeOrder, ChangeOrder.ID_ChangeOrder, ids["co_ref"]),
            (ChangeOrder, ChangeOrder.ID_ChangeOrder, ids["co_order"]),
            (ChangeOrder, ChangeOrder.ID_ChangeOrder, ids["co_job"]),
            (Order, Order.ID_Order, ids["order"]),
            (JobMemberLink, JobMemberLink.job_id, ids["job"]),
            (Job, Job.ID_Jobs, ids["job"]),
            (Job, Job.ID_Jobs, ids["survivor"]),
        ):
            for row in s.exec(select(model).where(col == val)).all():
                s.delete(row)
        s.commit()


def _post_delete(client, item_id):
    token = config("PODIO_WEBHOOK_TOKEN", default="")
    return client.post(f"/webhook/podio/jobs/QID/2026?token={token}",
                       json={"type": "item.delete", "item_id": item_id})


def _assert_sin_rastro(ids):
    with get_session() as s:
        assert s.exec(select(Job).where(Job.ID_Jobs == ids["job"])).first() is None
        assert s.exec(select(Order).where(
            Order.ID_Order == ids["order"])).first() is None
        for co in (ids["co_ref"], ids["co_order"], ids["co_job"]):
            assert s.exec(select(ChangeOrder).where(
                ChangeOrder.ID_ChangeOrder == co)).first() is None, f"CO {co} huérfano"
        assert s.exec(select(FinancialDocument).where(
            FinancialDocument.ID_FinancialDoc == ids["fdoc"])).first() is None
        est = s.exec(select(EstimateCost).where(
            EstimateCost.ID_EstimateCost == ids["est"])).first()
        assert est is not None and est.ID_Order is None
        assert s.exec(select(JobMemberLink).where(
            JobMemberLink.job_id == ids["job"])).first() is None


def test_delete_borra_cos_por_las_tres_vias(client, world):
    """failed_sync #12: los COs enlazados solo por ID_Order/ID_Jobs quedaban
    fuera del filtro job_podio_id y reventaban el flush del ORM."""
    resp = _post_delete(client, world["item"])
    assert resp.status_code == 200, resp.get_data(as_text=True)[:400]
    _assert_sin_rastro(world)


def test_delete_es_idempotente(client, world):
    """Podio reenvía webhooks: el segundo delete no puede fallar."""
    assert _post_delete(client, world["item"]).status_code == 200
    resp = _post_delete(client, world["item"])
    assert resp.status_code == 200, resp.get_data(as_text=True)[:400]
    _assert_sin_rastro(world)


def test_carrera_panel_y_webhook(client, admin_headers, world):
    """El panel borra con ?force=true y Podio manda su webhook: el segundo
    en llegar debe salir limpio, no con StaleDataError."""
    resp = client.delete(f"/jobs/{world['job']}?force=true", headers=admin_headers)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:400]
    resp = _post_delete(client, world["item"])
    assert resp.status_code == 200, resp.get_data(as_text=True)[:400]
    _assert_sin_rastro(world)
