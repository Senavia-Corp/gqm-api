"""Cobertura B7 (críticos del pr-test-analyzer): scoping e IDOR de Tasks
+ brazo technician del scoping de jobs."""
import uuid

import pytest
from decouple import config
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.JobModel import Job
from src.models.TasksModel import Tasks
from src.models.link_models.JobSubcontractor import JobSubcontractorLink
from src.models.link_models.JobTechnician import JobTechnicianLink


def _login(app, email):
    resp = app.test_client().post("/auth/login", json={
        "Email_Address": email, "Password": config("SEED_DEV_PASSWORD")})
    assert resp.status_code == 200
    data = resp.get_json()
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user_id"]


@pytest.fixture(scope="module")
def sub(app):
    return _login(app, "sub-dev@senavia-test.com")


@pytest.fixture(scope="module")
def tech(app):
    return _login(app, "tech-dev@senavia-test.com")


@pytest.fixture(scope="module")
def member(app):
    return _login(app, "member-dev@senavia-test.com")


@pytest.fixture()
def world(sub, tech):
    """Un job del sub (con su tech asignado + una task) y un job ajeno con task."""
    _, sub_id = sub
    _, tech_id = tech
    sfx = uuid.uuid4().int % 90000 + 10000
    mine, other = f"QID5{sfx}", f"QID4{sfx}"
    t_mine, t_other = f"TSKT{sfx}A", f"TSKT{sfx}B"
    with get_session() as s:
        s.add(Job(ID_Jobs=mine, Job_type="QID", Project_name="Del sub"))
        s.add(Job(ID_Jobs=other, Job_type="QID", Project_name="Ajeno"))
        s.add(JobSubcontractorLink(job_id=mine, subcontr_id=sub_id))
        s.add(JobTechnicianLink(job_id=mine, technician_id=tech_id))
        s.add(Tasks(ID_Tasks=t_mine, Name="Mía", ID_Jobs=mine, ID_Technician=tech_id))
        s.add(Tasks(ID_Tasks=t_other, Name="Ajena", ID_Jobs=other))
        s.commit()
    yield {"mine": mine, "other": other, "t_mine": t_mine, "t_other": t_other}
    with get_session() as s:
        for tid in (t_mine, t_other):
            row = s.get(Tasks, tid)
            if row:
                s.delete(row)
        for link_model, jid in ((JobSubcontractorLink, mine), (JobTechnicianLink, mine)):
            for row in s.exec(select(link_model).where(link_model.job_id == jid)).all():
                s.delete(row)
        for jid in (mine, other):
            row = s.exec(select(Job).where(Job.ID_Jobs == jid)).first()
            if row:
                s.delete(row)
        s.commit()


def _task_ids(resp):
    data = resp.get_json()
    rows = data if isinstance(data, list) else data.get("results", [])
    return {r["ID_Tasks"] for r in rows}


def test_sub_only_sees_their_tasks(client, sub, world):
    headers, _ = sub
    resp = client.get("/tasks/?limit=500", headers=headers)
    assert resp.status_code == 200
    ids = _task_ids(resp)
    assert world["t_mine"] in ids
    assert world["t_other"] not in ids


def test_tech_only_sees_their_tasks(client, tech, world):
    headers, _ = tech
    resp = client.get("/tasks/?limit=500", headers=headers)
    assert resp.status_code == 200
    ids = _task_ids(resp)
    assert world["t_mine"] in ids
    assert world["t_other"] not in ids


def test_portal_gets_404_on_foreign_task(client, sub, tech, world):
    for headers, _ in (sub, tech):
        assert client.get(f"/tasks/{world['t_other']}", headers=headers).status_code == 404
        assert client.get(f"/tasks/{world['t_mine']}", headers=headers).status_code == 200


def test_sub_cannot_create_task_on_foreign_job(client, sub, world):
    headers, _ = sub
    resp = client.post("/tasks/", headers=headers, json={
        "Name": "Intrusa", "ID_Jobs": world["other"]})
    assert resp.status_code == 403


def test_tech_cannot_create_tasks_at_all(client, tech, world):
    headers, _ = tech
    resp = client.post("/tasks/", headers=headers, json={
        "Name": "Intrusa", "ID_Jobs": world["mine"]})
    assert resp.status_code == 403  # la política Technical no tiene tasks:create


def test_portal_cannot_reassign_task_to_foreign_job(client, sub, world):
    """Post-update re-check: mover la tarea propia a un job ajeno → 403."""
    headers, _ = sub
    resp = client.patch(f"/tasks/{world['t_mine']}", headers=headers,
                        json={"ID_Jobs": world["other"]})
    assert resp.status_code == 403
    with get_session() as s:
        assert s.get(Tasks, world["t_mine"]).ID_Jobs == world["mine"]


def test_portal_cannot_update_foreign_task(client, sub, world):
    headers, _ = sub
    resp = client.patch(f"/tasks/{world['t_other']}", headers=headers,
                        json={"Task_status": "Completed"})
    assert resp.status_code == 404


def test_tech_scoping_on_jobs(client, tech, world):
    """Brazo technician de scope_jobs_statement (antes solo se probaba sub)."""
    headers, _ = tech
    resp = client.get("/jobs/?limit=200", headers=headers)
    assert resp.status_code == 200
    ids = [j["ID_Jobs"] for j in resp.get_json()["results"]]
    assert world["mine"] in ids
    assert world["other"] not in ids
    assert client.get(f"/jobs/{world['other']}", headers=headers).status_code == 404


def test_member_cannot_force_delete(client, member, world):
    """job:force_delete está denegado a GQM Member (crítico #3)."""
    headers, _ = member
    with get_session() as s:
        from src.models.OrderModel import Order
        s.add(Job(ID_Jobs=f"{world['mine']}F", Job_type="QID",
                  podio_item_id=f"88{world['mine'][4:]}"))
        s.add(Order(ID_Order=f"ORDF{world['mine'][4:]}",
                    job_podio_id=f"88{world['mine'][4:]}",
                    tech_field="tech-1-ptl-original-pricing", Formula=10.0))
        s.commit()
    try:
        resp = client.delete(f"/jobs/{world['mine']}F?force=true", headers=headers)
        assert resp.status_code == 403
    finally:
        with get_session() as s:
            from src.models.OrderModel import Order
            for row in s.exec(select(Order).where(
                    Order.ID_Order == f"ORDF{world['mine'][4:]}")).all():
                s.delete(row)
            row = s.exec(select(Job).where(Job.ID_Jobs == f"{world['mine']}F")).first()
            if row:
                s.delete(row)
            s.commit()
