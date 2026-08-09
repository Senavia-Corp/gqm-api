"""REG-057/REG-118: el webhook QBO ya no se traga errores — dead-letter + retry."""
import uuid

from sqlmodel import select

import src.routes.Webhook_bp as wb
from src.database.db_sqlmodel import get_session
from src.models.QboFailedEventModel import QboFailedEvent


def _cleanup(entity_id):
    with get_session() as session:
        for row in session.exec(select(QboFailedEvent).where(
                QboFailedEvent.entity_id == entity_id)).all():
            session.delete(row)
        session.commit()


def test_failed_event_recorded_and_retried(client, admin_headers, monkeypatch):
    entity_id = str(990000 + uuid.uuid4().int % 9999)

    def _boom(**kwargs):
        raise RuntimeError("QBO caído (simulado)")

    monkeypatch.setattr(wb, "process_single_entity_qbo", _boom)
    try:
        # 1. el fallo NO revienta y queda en la dead-letter
        assert wb._process_event("realm-test", "Invoice", entity_id, "Update") is False
        with get_session() as session:
            row = session.exec(select(QboFailedEvent).where(
                QboFailedEvent.entity_id == entity_id)).first()
            assert row is not None and row.resolved is False
            assert "RuntimeError" in (row.error_message or "")
            row_id = row.id

        # 2. retry con QBO aún caído → 502 y sigue pendiente
        resp = client.post(f"/webhook/qbo/failed_events/{row_id}/retry",
                           headers=admin_headers)
        assert resp.status_code == 502

        # 3. QBO se recupera → retry 200 y resolved
        monkeypatch.setattr(wb, "process_single_entity_qbo", lambda **kw: None)
        resp = client.post(f"/webhook/qbo/failed_events/{row_id}/retry",
                           headers=admin_headers)
        assert resp.status_code == 200
        with get_session() as session:
            assert session.get(QboFailedEvent, row_id).resolved is True
    finally:
        _cleanup(entity_id)
