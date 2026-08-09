"""REG-012: PAR no admite Change Orders — rechazo explícito 422, nunca
guardado silencioso solo en BD."""
import uuid

from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.ChangeOrderModel import ChangeOrder
from src.models.JobModel import Job


def test_par_change_order_returns_422_and_saves_nothing(client, admin_headers):
    suffix = uuid.uuid4().int % 90000 + 10000
    tracking = f"PAR8{suffix}"
    podio_id = str(870000000 + suffix)
    with get_session() as session:
        session.add(Job(ID_Jobs=tracking, Job_type="PAR",
                        podio_item_id=podio_id, podio_app_year=2026))
        session.commit()
    try:
        resp = client.post(
            "/change_order/",
            json={"Name": "CO prohibido", "ChangeOrderFormula": 100.0,
                  "job_podio_id": podio_id},
            headers=admin_headers,
        )
        assert resp.status_code == 422
        assert "PAR" in resp.get_data(as_text=True)

        with get_session() as session:
            saved = session.exec(select(ChangeOrder).where(
                ChangeOrder.job_podio_id == podio_id)).all()
            assert saved == []
    finally:
        with get_session() as session:
            job = session.exec(select(Job).where(Job.ID_Jobs == tracking)).first()
            if job:
                session.delete(job)
            session.commit()
