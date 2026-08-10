"""Idempotencia del webhook de jobs bajo entregas duplicadas/concurrentes.

Podio reintenta los hooks y una misma app puede tener VARIOS hooks activos
apuntando al mismo endpoint (verificado en las apps TEST: taskipos + ngrok),
así que el mismo evento llega dos veces y en paralelo. El perdedor de la
carrera reventaba con UniqueViolation → 500 → Podio reintenta → dead-letter
llena de ruido para el cliente.
"""
import threading
import uuid

import pytest
from decouple import config
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.JobModel import Job

from tests.fixtures.podio_items import qid_item


@pytest.fixture()
def item_ids():
    sfx = uuid.uuid4().int % 90000 + 10000
    item_id, tracking = 930000000 + sfx, f"QIDX{sfx}"
    yield item_id, tracking
    with get_session() as s:
        for row in s.exec(select(Job).where(
                Job.podio_item_id == str(item_id))).all():
            s.delete(row)
        for row in s.exec(select(Job).where(Job.ID_Jobs == tracking)).all():
            s.delete(row)
        s.commit()


def _url():
    return f"/webhook/podio/jobs/QID/2026?token={config('PODIO_WEBHOOK_TOKEN', default='')}"


def _payload(item_id, tracking):
    return {"type": "item.create", "item_id": item_id,
            "item": qid_item(item_id=item_id, tracking_id=tracking)}


def test_entrega_duplicada_secuencial(client, item_ids):
    """Dos entregas del mismo item.create: ambas 200, un solo job."""
    item_id, tracking = item_ids
    body = _payload(item_id, tracking)
    r1 = client.post(_url(), json=body)
    r2 = client.post(_url(), json=body)
    assert r1.status_code == 200, r1.get_data(as_text=True)[:300]
    assert r2.status_code == 200, r2.get_data(as_text=True)[:300]
    with get_session() as s:
        jobs = s.exec(select(Job).where(Job.podio_item_id == str(item_id))).all()
        assert len(jobs) == 1, f"se esperaba 1 job, hay {len(jobs)}"


def test_entrega_concurrente(app, item_ids):
    """Dos hooks entregando a la vez (el caso real de las apps TEST):
    nadie puede devolver 500 y debe quedar exactamente un job."""
    item_id, tracking = item_ids
    body = _payload(item_id, tracking)
    barrier = threading.Barrier(2)
    results = []

    def enviar():
        c = app.test_client()
        barrier.wait(timeout=10)
        try:
            results.append(c.post(_url(), json=body).status_code)
        except Exception as e:  # noqa: BLE001
            results.append(f"EXC {e}")

    hilos = [threading.Thread(target=enviar) for _ in range(2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=90)

    assert all(r == 200 for r in results), f"status de las entregas: {results}"
    with get_session() as s:
        jobs = s.exec(select(Job).where(Job.podio_item_id == str(item_id))).all()
        assert len(jobs) == 1, f"se esperaba 1 job, hay {len(jobs)}"


def test_delete_duplicado(client, item_ids):
    """Podio reenvía el item.delete: la segunda vez ya no hay nada que
    borrar y aun así debe ser 200 (estado convergido), no 500."""
    item_id, tracking = item_ids
    assert client.post(_url(), json=_payload(item_id, tracking)).status_code == 200
    borrar = {"type": "item.delete", "item_id": item_id}
    r1 = client.post(_url(), json=borrar)
    r2 = client.post(_url(), json=borrar)
    assert r1.status_code == 200, r1.get_data(as_text=True)[:300]
    assert r2.status_code == 200, r2.get_data(as_text=True)[:300]
    with get_session() as s:
        assert s.exec(select(Job).where(
            Job.podio_item_id == str(item_id))).first() is None
