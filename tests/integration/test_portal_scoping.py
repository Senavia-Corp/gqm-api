"""REG-037/110/111: los roles de portal solo ven lo suyo."""
import uuid

import pytest
from decouple import config
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.JobModel import Job
from src.models.link_models.JobSubcontractor import JobSubcontractorLink


@pytest.fixture(scope="module")
def sub_session(app):
    client = app.test_client()
    resp = client.post("/auth/login", json={
        "Email_Address": "sub-dev@senavia-test.com",
        "Password": config("SEED_DEV_PASSWORD"),
    })
    assert resp.status_code == 200
    data = resp.get_json()
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user_id"]


@pytest.fixture()
def two_jobs(sub_session):
    _, sub_id = sub_session
    suffix = uuid.uuid4().int % 90000 + 10000
    mine, other = f"QID7{suffix}", f"QID6{suffix}"
    with get_session() as session:
        session.add(Job(ID_Jobs=mine, Job_type="QID", Project_name="Job del sub"))
        session.add(Job(ID_Jobs=other, Job_type="QID", Project_name="Job ajeno"))
        session.add(JobSubcontractorLink(job_id=mine, subcontr_id=sub_id,
                                         position="technician-2"))
        session.commit()
    yield mine, other
    with get_session() as session:
        for link in session.exec(select(JobSubcontractorLink).where(
                JobSubcontractorLink.job_id == mine)).all():
            session.delete(link)
        for jid in (mine, other):
            job = session.exec(select(Job).where(Job.ID_Jobs == jid)).first()
            if job:
                session.delete(job)
        session.commit()


def test_sub_list_only_contains_their_jobs(client, sub_session, two_jobs):
    headers, _ = sub_session
    mine, other = two_jobs
    resp = client.get("/jobs/?limit=200", headers=headers)
    assert resp.status_code == 200
    ids = [j["ID_Jobs"] for j in resp.get_json()["results"]]
    assert mine in ids
    assert other not in ids


def test_sub_cannot_read_foreign_job(client, sub_session, two_jobs):
    headers, _ = sub_session
    mine, other = two_jobs
    assert client.get(f"/jobs/{mine}", headers=headers).status_code == 200
    # 404 para no filtrar existencia
    assert client.get(f"/jobs/{other}", headers=headers).status_code == 404


def test_sub_cannot_query_other_subs_orders(client, sub_session, two_jobs):
    headers, _ = sub_session
    mine, _ = two_jobs
    resp = client.get(f"/order/subcontractor/SUBC-OTRO/job/{mine}", headers=headers)
    assert resp.status_code == 403
