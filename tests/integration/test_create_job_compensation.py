"""REG-013: si el guardado local falla tras crear el item en Podio,
create_job debe borrar el item remoto (no dejar huérfanos)."""
import pytest


class _FakePodioService:
    def __init__(self):
        self.created = []
        self.deleted = []

    def create_item(self, fields):
        self.created.append(fields)
        return {"item_id": 887700111}

    def get_item(self, item_id):
        return {"item_id": item_id, "app_item_id_formatted": "QID88888"}

    def delete_item(self, item_id):
        self.deleted.append(str(item_id))


@pytest.fixture()
def fake_podio(monkeypatch):
    import src.routes.Job as job_module

    fake = _FakePodioService()
    monkeypatch.setattr(
        job_module.podio_jobs_router, "get_service", lambda job_type, year: fake)
    return fake


def test_local_save_failure_compensates_podio_item(client, admin_headers, fake_podio, monkeypatch):
    import src.routes.Job as job_module

    def _boom(session, obj, max_retries=3):
        raise RuntimeError("fallo local simulado")

    monkeypatch.setattr(job_module, "save_with_retry", _boom)

    resp = client.post(
        "/jobs/?sync_podio=true&year=2026",
        json={"Job_type": "QID", "Project_name": "Compensación test"},
        headers=admin_headers,
    )

    assert resp.status_code >= 400
    assert fake_podio.created, "debió crear el item en Podio"
    assert fake_podio.deleted == ["887700111"], "debió compensar borrando el item"
