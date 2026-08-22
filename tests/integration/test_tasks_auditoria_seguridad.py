"""Hallazgos de la auditoría de Tasks (22-ago-2026).

T-02  /tlactivity se protege con el vocabulario `tasks` y sin scoping →
      un rol de portal puede leer el log entero, FABRICAR entradas y ALTERARLAS.
T-26  la guarda post-update no frena al TÉCNICO: `task_belongs_to_portal_user`
      solo mira ID_Technician, que no cambia al reasignar ID_Jobs.
T-27  GET /jobs/by-type-year no aplica scoping de portal ni serialize_job →
      devuelve TODOS los jobs con su bloque financiero a cualquier rol.

Cada test falla ANTES del arreglo y pasa DESPUÉS.
"""
import uuid

import pytest
from decouple import config
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.JobModel import Job
from src.models.TasksModel import Tasks
from src.models.TLActivityModel import TLActivity
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
def admin(app):
    return _login(app, "admin-dev@senavia-test.com")


@pytest.fixture()
def mundo(sub, tech):
    _, sub_id = sub
    _, tech_id = tech
    sfx = uuid.uuid4().int % 90000 + 10000
    mio, ajeno = f"QID5{sfx}", f"QID4{sfx}"
    t_mio = f"TSKS{sfx}"
    with get_session() as s:
        s.add(Job(ID_Jobs=mio, Job_type="QID", Project_name="Del sub",
                  podio_app_year=2026, Gqm_final_sold_pricing=123456.78))
        s.add(Job(ID_Jobs=ajeno, Job_type="QID", Project_name="Ajeno",
                  podio_app_year=2026, Gqm_final_sold_pricing=999999.99))
        s.add(JobSubcontractorLink(job_id=mio, subcontr_id=sub_id))
        s.add(JobTechnicianLink(job_id=mio, technician_id=tech_id))
        s.add(Tasks(ID_Tasks=t_mio, Name="Mía", ID_Jobs=mio, ID_Technician=tech_id))
        s.commit()
    yield {"mio": mio, "ajeno": ajeno, "t_mio": t_mio}
    with get_session() as s:
        fila = s.get(Tasks, t_mio)
        if fila:
            s.delete(fila)
        for modelo, jid in ((JobSubcontractorLink, mio), (JobTechnicianLink, mio)):
            for f in s.exec(select(modelo).where(modelo.job_id == jid)).all():
                s.delete(f)
        for jid in (mio, ajeno):
            f = s.exec(select(Job).where(Job.ID_Jobs == jid)).first()
            if f:
                s.delete(f)
        s.commit()


# ── T-26 ──────────────────────────────────────────────────────────────────────
def test_tecnico_no_puede_reasignar_su_tarea_a_job_ajeno(client, tech, mundo):
    """El sub ya estaba cubierto; el TÉCNICO no lo estaba y sí podía."""
    headers, _ = tech
    resp = client.patch(f"/tasks/{mundo['t_mio']}", headers=headers,
                        json={"ID_Jobs": mundo["ajeno"]})
    assert resp.status_code == 403, "el técnico reasignó su tarea a un job ajeno"
    with get_session() as s:
        assert s.get(Tasks, mundo["t_mio"]).ID_Jobs == mundo["mio"]


# ── T-02 ──────────────────────────────────────────────────────────────────────
def test_portal_no_puede_fabricar_auditoria(client, sub):
    headers, _ = sub
    marca = f"falsificada-{uuid.uuid4().hex[:8]}"
    try:
        resp = client.post("/tlactivity/", headers=headers,
                           json={"Action": marca, "Description": "inyectada"})
        assert resp.status_code == 403, "un subcontratista fabricó una entrada de auditoría"
        with get_session() as s:
            assert not s.exec(select(TLActivity)
                              .where(TLActivity.Action == marca)).all()
    finally:
        # si el arreglo falla, no dejamos basura que envenene la siguiente corrida
        with get_session() as s:
            for f in s.exec(select(TLActivity)
                            .where(TLActivity.Action == marca)).all():
                s.delete(f)
            s.commit()


def test_portal_no_puede_alterar_auditoria(client, sub, tech):
    with get_session() as s:
        muestra = s.exec(select(TLActivity)).first()
    if muestra is None:
        pytest.skip("no hay filas en tlactivity")
    for headers, _ in (sub, tech):
        resp = client.patch(f"/tlactivity/{muestra.ID_TLActivity}", headers=headers,
                            json={"Description": "alterada"})
        assert resp.status_code == 403, "un rol de portal alteró la auditoría"


def test_portal_no_puede_leer_el_log_completo(client, sub, tech):
    for headers, _ in (sub, tech):
        resp = client.get("/tlactivity/", headers=headers)
        assert resp.status_code == 403, "un rol de portal leyó el timeline completo"


def test_staff_sigue_leyendo_el_timeline_por_job(client, admin, mundo):
    """El arreglo no debe romper el consumidor real del panel."""
    headers, _ = admin
    resp = client.get(f"/tlactivity/job/{mundo['mio']}", headers=headers)
    assert resp.status_code in (200, 404)


# ── T-27 ──────────────────────────────────────────────────────────────────────
def test_by_type_year_respeta_el_scoping_de_portal(client, tech, sub, mundo):
    """El técnico no está asignado al job ajeno: no debe verlo por esta puerta."""
    for headers, _ in (tech, sub):
        resp = client.get("/jobs/by-type-year?type=QID&year=2026&limit=200", headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()
        filas = data if isinstance(data, list) else data.get("results", [])
        vistos = {j["ID_Jobs"] for j in filas}
        assert mundo["ajeno"] not in vistos, (
            f"by-type-year expuso el job ajeno {mundo['ajeno']}")


def test_by_type_year_no_filtra_el_bloque_financiero_al_tecnico(client, tech, mundo):
    headers, _ = tech
    resp = client.get("/jobs/by-type-year?type=QID&year=2026&limit=200", headers=headers)
    data = resp.get_json()
    filas = data if isinstance(data, list) else data.get("results", [])
    for j in filas:
        assert "Gqm_final_sold_pricing" not in j, (
            "by-type-year entregó precios de venta a un técnico (solo tiene job:read_basics)")


# ── T-09 ──────────────────────────────────────────────────────────────────────
def test_tarea_de_certificado_no_se_duplica(client, admin, sub):
    """El dedupe vivía en localStorage: por navegador y por dispositivo."""
    headers, _ = admin
    _, sub_id = sub
    nombre = f"Update Certificate {uuid.uuid4().hex[:6]} - Expire in 30 days"
    payload = {"Name": nombre, "Task_status": "Not started",
               "Priority": "High", "ID_Subcontractor": sub_id}
    try:
        primero = client.post("/tasks/", headers=headers, json=payload)
        assert primero.status_code == 201
        tid = primero.get_json()["ID_Tasks"]

        for _ in range(2):
            repe = client.post("/tasks/", headers=headers, json=payload)
            assert repe.status_code == 200, "creó un duplicado en vez de devolver la existente"
            assert repe.get_json()["ID_Tasks"] == tid

        with get_session() as s:
            filas = s.exec(select(Tasks).where(Tasks.Name == nombre)).all()
            assert len(filas) == 1, f"quedaron {len(filas)} filas idénticas"
    finally:
        with get_session() as s:
            for f in s.exec(select(Tasks).where(Tasks.Name == nombre)).all():
                s.delete(f)
            s.commit()


# ── Actor de portal ───────────────────────────────────────────────────────────
def test_la_accion_de_un_sub_queda_atribuida(client, sub, mundo):
    """tlactivity tiene ID_Subcontractor, pero solo se rellenaba ID_Member:
    toda acción de portal se auditaba sin autor."""
    headers, sub_id = sub
    nombre = f"AUDIT actor {uuid.uuid4().hex[:6]}"
    try:
        resp = client.post("/tasks/", headers=headers,
                           json={"Name": nombre, "ID_Jobs": mundo["mio"]})
        assert resp.status_code == 201
        with get_session() as s:
            ev = s.exec(select(TLActivity)
                        .where(TLActivity.Action == "Task created")
                        .order_by(TLActivity.Action_datetime.desc())).first()
            assert ev is not None
            assert ev.ID_Subcontractor == sub_id, "la acción del sub quedó sin autor"
            assert ev.ID_Jobs == mundo["mio"], "el evento no cuelga del job"
    finally:
        with get_session() as s:
            for f in s.exec(select(Tasks).where(Tasks.Name == nombre)).all():
                s.delete(f)
            s.commit()


# ── Validación: debe ser 400 con motivo, no 500 mudo ──────────────────────────
@pytest.mark.parametrize("cuerpo,fragmento", [
    ({}, "ID_Jobs o ID_Subcontractor"),
    ({"Name": "x", "Task_status": "Not Started"}, "Task_status"),
    ({"Name": "x", "Priority": "Critical"}, "Priority"),
])
def test_los_errores_de_validacion_son_400_con_motivo(client, admin, mundo,
                                                      cuerpo, fragmento):
    """ve.errors() lleva la excepción original en `ctx`, que NO es serializable:
    jsonify reventaba y Flask devolvía un 500 mudo en vez del 400 con detalle."""
    headers, _ = admin
    payload = {**cuerpo}
    if "Name" in payload:
        payload.setdefault("ID_Jobs", mundo["mio"])
    resp = client.post("/tasks/", headers=headers, json=payload)
    assert resp.status_code == 400, f"esperaba 400, llegó {resp.status_code}"
    cuerpo_resp = resp.get_json()
    assert cuerpo_resp["code"] == "validation_error"
    texto = str(cuerpo_resp["errors"])
    assert fragmento in texto, f"el motivo no menciona {fragmento!r}: {texto[:200]}"
