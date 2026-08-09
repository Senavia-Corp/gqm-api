"""REG-014: delete_job con hijos → 409; ?force=true cascadea sin huérfanos."""
import uuid

from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.ChangeOrderModel import ChangeOrder
from src.models.FinancialDocModel import FinancialDocument
from src.models.JobModel import Job
from src.models.OrderModel import Order


def _seed_job_with_children():
    suffix = uuid.uuid4().int % 90000 + 10000
    tracking = f"QID8{suffix}"
    podio_id = str(880000000 + suffix)
    with get_session() as session:
        session.add(Job(ID_Jobs=tracking, Job_type="QID",
                        podio_item_id=podio_id, podio_app_year=2026))
        session.add(Order(ID_Order=f"ORDT{suffix}", job_podio_id=podio_id,
                          tech_field="tech-1-ptl-original-pricing", Formula=100.0))
        session.add(ChangeOrder(ID_ChangeOrder=f"COT{suffix}",
                                job_podio_id=podio_id, ChangeOrderFormula=50.0))
        session.add(FinancialDocument(
            ID_FinancialDoc=f"FDT{suffix}", ID_Jobs=tracking,
            Type_of_document="Invoice"))
        session.commit()
    return tracking, podio_id


def _counts(tracking, podio_id):
    with get_session() as session:
        return (
            len(session.exec(select(Order).where(Order.job_podio_id == podio_id)).all()),
            len(session.exec(select(ChangeOrder).where(ChangeOrder.job_podio_id == podio_id)).all()),
            len(session.exec(select(FinancialDocument).where(FinancialDocument.ID_Jobs == tracking)).all()),
            session.exec(select(Job).where(Job.ID_Jobs == tracking)).first() is not None,
        )


def _cleanup(tracking, podio_id):
    with get_session() as session:
        for model, col, key in (
            (ChangeOrder, ChangeOrder.job_podio_id, podio_id),
            (Order, Order.job_podio_id, podio_id),
            (FinancialDocument, FinancialDocument.ID_Jobs, tracking),
        ):
            for row in session.exec(select(model).where(col == key)).all():
                session.delete(row)
        job = session.exec(select(Job).where(Job.ID_Jobs == tracking)).first()
        if job:
            session.delete(job)
        session.commit()


def test_delete_with_children_needs_force(client, admin_headers):
    tracking, podio_id = _seed_job_with_children()
    try:
        resp = client.delete(f"/jobs/{tracking}", headers=admin_headers)
        assert resp.status_code == 409
        assert "force=true" in resp.get_data(as_text=True)
        assert _counts(tracking, podio_id) == (1, 1, 1, True)
    finally:
        _cleanup(tracking, podio_id)


def test_force_delete_cascades_without_orphans(client, admin_headers):
    tracking, podio_id = _seed_job_with_children()
    try:
        resp = client.delete(f"/jobs/{tracking}?force=true", headers=admin_headers)
        assert resp.status_code == 200
        assert _counts(tracking, podio_id) == (0, 0, 0, False)
    finally:
        _cleanup(tracking, podio_id)
