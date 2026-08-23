"""REG-037/110/111: los roles de portal solo ven lo suyo."""
import io
import uuid
from datetime import datetime

import pytest
from decouple import config
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.ClientModel import Client
from src.models.JobModel import Job
from src.models.link_models.JobMember import JobMemberLink
from src.models.link_models.JobSubcontractor import JobSubcontractorLink
from src.models.link_models.JobTechnician import JobTechnicianLink


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


@pytest.fixture(scope="module")
def tech_session(app):
    client = app.test_client()
    resp = client.post("/auth/login", json={
        "Email_Address": "tech-dev@senavia-test.com",
        "Password": config("SEED_DEV_PASSWORD"),
    })
    assert resp.status_code == 200
    data = resp.get_json()
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user_id"]


@pytest.fixture(scope="module")
def admin_id(app):
    client = app.test_client()
    resp = client.post("/auth/login", json={
        "Email_Address": "admin-dev@senavia-test.com",
        "Password": config("SEED_DEV_PASSWORD"),
    })
    assert resp.status_code == 200
    return resp.get_json()["user_id"]


@pytest.fixture()
def two_jobs(sub_session, tech_session, admin_id):
    """Un job del sub (con su técnico y un PM) y uno ajeno, ambos con el mismo
    status/tipo/cliente/PM para que cada ruta de listado tenga que FILTRAR."""
    _, sub_id = sub_session
    _, tech_id = tech_session
    suffix = uuid.uuid4().int % 90000 + 10000
    mine, other = f"QID7{suffix}", f"QID6{suffix}"
    with get_session() as session:
        cliente = session.exec(select(Client).where(
            Client.ID_Community_Tracking.is_not(None))).first()
        assert cliente, "develop necesita un cliente con ID_Community_Tracking"
        id_client, pmc = cliente.ID_Client, cliente.ID_Community_Tracking  # antes del commit (expire)
        comun = dict(Job_type="QID", Job_status="RBAC-TEST", ID_Client=id_client,
                     Gqm_formula_pricing=123.45)
        session.add(Job(ID_Jobs=mine, Project_name="Job del sub",
                        Date_assigned=datetime(1999, 1, 2), **comun))
        session.add(Job(ID_Jobs=other, Project_name="Job ajeno",
                        Date_assigned=datetime(1998, 1, 2), **comun))  # más antiguo
        session.add(JobSubcontractorLink(job_id=mine, subcontr_id=sub_id,
                                         position="technician-2"))
        session.add(JobTechnicianLink(job_id=mine, technician_id=tech_id))
        for jid in (mine, other):
            session.add(JobMemberLink(job_id=jid, member_id=admin_id, rol="PM"))
        session.commit()
    yield mine, other, pmc, id_client, admin_id
    with get_session() as session:
        for modelo in (JobSubcontractorLink, JobTechnicianLink, JobMemberLink):
            for link in session.exec(select(modelo).where(modelo.job_id.in_((mine, other)))).all():
                session.delete(link)
        for jid in (mine, other):
            job = session.exec(select(Job).where(Job.ID_Jobs == jid)).first()
            if job:
                session.delete(job)
        session.commit()


def test_sub_list_only_contains_their_jobs(client, sub_session, two_jobs):
    headers, _ = sub_session
    mine, other = two_jobs[:2]
    resp = client.get("/jobs/?limit=200", headers=headers)
    assert resp.status_code == 200
    ids = [j["ID_Jobs"] for j in resp.get_json()["results"]]
    assert mine in ids
    assert other not in ids


def test_sub_cannot_read_foreign_job(client, sub_session, two_jobs):
    headers, _ = sub_session
    mine, other = two_jobs[:2]
    assert client.get(f"/jobs/{mine}", headers=headers).status_code == 200
    # 404 para no filtrar existencia
    assert client.get(f"/jobs/{other}", headers=headers).status_code == 404


def test_sub_cannot_query_other_subs_orders(client, sub_session, two_jobs):
    headers, _ = sub_session
    mine = two_jobs[0]
    resp = client.get(f"/order/subcontractor/SUBC-OTRO/job/{mine}", headers=headers)
    assert resp.status_code == 403


def _ids(body):
    if isinstance(body, dict):
        body = body.get("results", [])
    return {j["ID_Jobs"] for j in body}


RUTAS_LISTADO = [
    "/jobs/status/RBAC-TEST?limit=100",
    "/jobs/type/QID?limit=100",
    "/jobs/date_assigned/1999-01-02?limit=100",
    "/jobs/client/{cliente}?limit=100",
    "/jobs/member/{pm}?limit=100",
    "/jobs/by-member-role?member_id={pm}&rol=PM&limit=100",
    "/jobs/subcontractor/{sub}?limit=100",
]


@pytest.mark.parametrize("ruta", RUTAS_LISTADO)
def test_sub_listados_scoped(client, sub_session, two_jobs, ruta):
    """Las 7 rutas de listado que no tenían scoping: solo lo suyo."""
    headers, sub_id = sub_session
    mine, other, _, cliente, pm = two_jobs
    resp = client.get(ruta.format(cliente=cliente, pm=pm, sub=sub_id), headers=headers)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
    ids = _ids(resp.get_json())
    assert mine in ids and other not in ids, f"{ruta}: {ids}"


def test_sub_oldest_scoped(client, sub_session, two_jobs):
    """Sin scoping /oldest devolvería `other` (1998); con scoping, `mine` (1999)."""
    headers, _ = sub_session
    mine, other, pmc, _, _ = two_jobs
    resp = client.get(f"/jobs/oldest?parent_mgmt_co_id={pmc}", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["ID_Jobs"] == mine


def test_sub_no_puede_pedir_jobs_de_otro_sub(client, sub_session, two_jobs):
    headers, _ = sub_session
    assert client.get("/jobs/subcontractor/SUBC-OTRO", headers=headers).status_code == 403


def test_sub_excel_solo_sus_jobs(client, sub_session, two_jobs):
    import openpyxl
    headers, _ = sub_session
    mine, other, *_ = two_jobs
    resp = client.post("/jobs_excel/export", headers=headers,
                       json={"filters": {"statuses": ["RBAC-TEST"]}})
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.data), read_only=True)
    celdas = {str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row}
    assert mine in celdas and other not in celdas


def test_tecnico_listados_basics(client, tech_session, two_jobs):
    """El técnico (job:read_basics) ve solo su job y sin claves financieras."""
    headers, _ = tech_session
    mine, other, *_ = two_jobs
    resp = client.get("/jobs/status/RBAC-TEST?limit=100", headers=headers)
    assert resp.status_code == 200
    filas = resp.get_json()["results"]
    assert {j["ID_Jobs"] for j in filas} == {mine}
    assert all("Gqm_formula_pricing" not in j for j in filas)


def test_tecnico_sin_excel_ni_chat(client, tech_session, two_jobs):
    headers, _ = tech_session
    mine, *_ = two_jobs
    assert client.post("/jobs_excel/export", headers=headers, json={}).status_code == 403
    assert client.get(f"/chat/job/{mine}", headers=headers).status_code == 403


def test_chat_scoped_para_sub(client, sub_session, two_jobs):
    headers, _ = sub_session
    mine, other, *_ = two_jobs
    assert client.get(f"/chat/job/{mine}", headers=headers).status_code == 200
    assert client.get(f"/chat/job/{other}", headers=headers).status_code == 404
