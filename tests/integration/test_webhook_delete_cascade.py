"""Cobertura B7: item.delete del webhook de jobs debe cascar igual que el
DELETE por API — findocs fuera, EstimateCost/Opportunities desenlazados de las
Orders (FK sin ondelete) y cero huérfanos."""
import uuid

from decouple import config
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.ChangeOrderModel import ChangeOrder
from src.models.EstimateCostModel import EstimateCost
from src.models.FinancialDocModel import FinancialDocument
from src.models.JobModel import Job
from src.models.MemberModel import Member
from src.models.OrderModel import Order
from src.models.TLActivityModel import TLActivity
from src.models.link_models.JobMember import JobMemberLink


def test_webhook_item_delete_cascades(client):
    sfx = uuid.uuid4().int % 90000 + 10000
    item_id = 910000000 + sfx
    tracking, survivor = f"QID8{sfx}", f"QID3{sfx}"
    order_id, co_id = f"ORDW{sfx}", f"CHOW{sfx}"
    fdoc_id, est_id = f"FDW{sfx}", f"ESTW{sfx}"

    with get_session() as s:
        s.add(Job(ID_Jobs=tracking, Job_type="QID", podio_item_id=str(item_id)))
        s.add(Job(ID_Jobs=survivor, Job_type="QID"))
        s.add(Order(ID_Order=order_id, job_podio_id=str(item_id), Formula=100.0))
        s.add(ChangeOrder(ID_ChangeOrder=co_id, job_podio_id=str(item_id),
                          ID_Order=order_id))
        s.add(FinancialDocument(ID_FinancialDoc=fdoc_id, ID_Jobs=tracking,
                                Type_of_document="Bill"))
        # Costo REASIGNADO a otro job pero aún enlazado a la orden condenada:
        # sin el unlink previo, el DELETE de la Order viola la FK.
        s.add(EstimateCost(ID_EstimateCost=est_id, ID_Jobs=survivor,
                           ID_Order=order_id))
        # Link a member: ejercita el pre-borrado bulk de links (workaround
        # StaleDataError, mismo patrón que delete_job del API)
        member = s.exec(select(Member)).first()
        if member:
            s.add(JobMemberLink(job_id=tracking, member_id=member.ID_Member,
                                rol="PM"))
        s.commit()

    try:
        token = config("PODIO_WEBHOOK_TOKEN", default="")
        resp = client.post(
            f"/webhook/podio/jobs/QID/2026?token={token}",
            json={"type": "item.delete", "item_id": item_id},
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)[:300]

        with get_session() as s:
            assert s.exec(select(Job).where(Job.ID_Jobs == tracking)).first() is None
            assert s.exec(select(Order).where(
                Order.ID_Order == order_id)).first() is None
            assert s.exec(select(ChangeOrder).where(
                ChangeOrder.ID_ChangeOrder == co_id)).first() is None
            assert s.exec(select(FinancialDocument).where(
                FinancialDocument.ID_FinancialDoc == fdoc_id)).first() is None
            est = s.exec(select(EstimateCost).where(
                EstimateCost.ID_EstimateCost == est_id)).first()
            assert est is not None and est.ID_Order is None
            # El rastro del delete SÍ persiste (sin FK al job borrado)
            tl = s.exec(select(TLActivity).where(
                TLActivity.Action == "Job deleted from Podio",
                TLActivity.Description.contains(tracking))).first()
            assert tl is not None, "el timeline del delete no persistió"
    finally:
        with get_session() as s:
            for tl in s.exec(select(TLActivity).where(
                    TLActivity.Description.contains(tracking))).all():
                s.delete(tl)
            for model, pk, val in (
                (EstimateCost, EstimateCost.ID_EstimateCost, est_id),
                (FinancialDocument, FinancialDocument.ID_FinancialDoc, fdoc_id),
                (ChangeOrder, ChangeOrder.ID_ChangeOrder, co_id),
                (Order, Order.ID_Order, order_id),
                (Job, Job.ID_Jobs, tracking),
                (Job, Job.ID_Jobs, survivor),
            ):
                row = s.exec(select(model).where(pk == val)).first()
                if row:
                    s.delete(row)
            s.commit()
