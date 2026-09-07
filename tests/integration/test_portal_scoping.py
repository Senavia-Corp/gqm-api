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
from src.models.AttachmentsModel import Attachments
from src.utils.portal_redaction import (CAMPOS_FINANCIEROS_JOB,
                                        CLIENTE_VISIBLE_A_PORTAL)


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
        # Centinelas, nunca NULL: con NULL, una respuesta sin datos financieros
        # no probaria nada — seria imposible distinguir «la ruta lo filtra» de
        # «la columna estaba vacia». Los dos ultimos son EXACTAMENTE los que
        # emite el diccionario a mano de /jobs/by-member-role.
        comun = dict(Job_type="QID", Job_status="RBAC-TEST", ID_Client=id_client,
                     Gqm_formula_pricing=123.45,
                     Gqm_premium_in_money=987.65, Gqm_target_return=543.21)
        session.add(Job(ID_Jobs=mine, Project_name="Job del sub",
                        Date_assigned=datetime(1999, 1, 2), **comun))
        session.add(Job(ID_Jobs=other, Project_name="Job ajeno",
                        Date_assigned=datetime(1998, 1, 2), **comun))  # más antiguo
        session.add(JobSubcontractorLink(job_id=mine, subcontr_id=sub_id,
                                         position="technician-2"))
        session.add(JobTechnicianLink(job_id=mine, technician_id=tech_id))
        for jid in (mine, other):
            session.add(JobMemberLink(job_id=jid, member_id=admin_id, rol="PM"))
        # La baraja de `access_level` sobre el job PROPIO: la regla de carpetas
        # solo se puede medir si existen las cuatro. `None` es el caso que
        # produce la sincronizacion desde Podio, que nunca escribe el campo.
        for nivel in ("technicians", "members", "logbook", None):
            session.add(Attachments(
                ID_Attachment=f"ATT-SCOPE-{suffix}-{nivel or 'null'}",
                Document_name=f"scoping-{nivel or 'null'}-{suffix}",
                Link=f"https://example.invalid/{nivel or 'null'}-{suffix}",
                Document_type="pdf", access_level=nivel, ID_Jobs=mine))
        session.commit()
    yield mine, other, pmc, id_client, admin_id
    with get_session() as session:
        # Los adjuntos primero: con la FK puesta, borrar el job antes revienta
        # y deja el mundo a medias para TODA prueba posterior del modulo.
        for att in session.exec(select(Attachments).where(
                Attachments.ID_Jobs.in_((mine, other)))).all():
            session.delete(att)
        session.commit()
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


# ─────────────────────────────────────────────────────────────────────────────
# Las dos rutas de /jobs que arman el diccionario A MANO y no pasan por
# `serialize_job`, y por tanto tampoco por la redacción central.
# ─────────────────────────────────────────────────────────────────────────────

def test_by_member_role_no_entrega_finanzas_al_sub(client, sub_session, two_jobs):
    """El sub NO recibe el margen de GQM en /jobs/by-member-role.

    Fugaba de verdad: el handler emitía `Gqm_premium_in_money` y
    `Gqm_target_return` a mano, y la única poda miraba el PERMISO `job:read`
    — que la política del subcontratista sí concede (seed_rbac.py:85), así que
    la rama era para el técnico y al sub no le llegaba nunca.
    """
    headers, _ = sub_session
    mine, _other, _pmc, _cli, pm = two_jobs
    resp = client.get(
        f"/jobs/by-member-role?member_id={pm}&rol=PM&limit=100", headers=headers)
    assert resp.status_code == 200
    filas = resp.get_json()["results"]
    assert mine in {f["ID_Jobs"] for f in filas}, "sin filas no se mide nada"
    for fila in filas:
        fugados = sorted(set(fila) & CAMPOS_FINANCIEROS_JOB)
        assert not fugados, f"{fila['ID_Jobs']} entrega {fugados}"


def test_by_member_role_el_staff_conserva_sus_finanzas(client, admin_headers, two_jobs):
    """El control: la poda es POR ROL DE PORTAL, no para todo el mundo.

    Sin esta prueba, una redacción escrita sin la guarda de rol pasaría la de
    arriba y le quitaría el margen al Full Admin en silencio.
    """
    mine, _other, _pmc, _cli, pm = two_jobs
    resp = client.get(
        f"/jobs/by-member-role?member_id={pm}&rol=PM&limit=100", headers=admin_headers)
    assert resp.status_code == 200
    filas = {f["ID_Jobs"]: f for f in resp.get_json()["results"]}
    assert mine in filas
    assert filas[mine]["Gqm_target_return"] == 543.21
    assert filas[mine]["Gqm_premium_in_money"] == 987.65


def test_oldest_es_seguro_por_construccion(client, sub_session, two_jobs):
    """/jobs/oldest tampoco pasa por `serialize_job`.

    Hoy no fuga —comprobado campo a campo—, así que esto no arregla nada: es un
    cerrojo. Se pone rojo el día que alguien amplíe su `load_only` con una
    columna financiera, que es la única forma en que esta ruta podría empezar
    a fugar.
    """
    headers, _ = sub_session
    mine, _other, pmc, _cli, _pm = two_jobs
    resp = client.get(f"/jobs/oldest?parent_mgmt_co_id={pmc}", headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ID_Jobs"] == mine, "debe darle el suyo, no el ajeno más antiguo"
    fugados = sorted(set(body) & CAMPOS_FINANCIEROS_JOB)
    assert not fugados, f"/jobs/oldest entrega {fugados}"
    assert set(body["client"]) <= CLIENTE_VISIBLE_A_PORTAL, body["client"]


# ─────────────────────────────────────────────────────────────────────────────
# Adjuntos: del job, el portal sólo ve y sólo escribe la carpeta «technicians».
# ─────────────────────────────────────────────────────────────────────────────

def _niveles_de(adjuntos):
    return sorted({(a.get("access_level") or "NULL") for a in adjuntos})


def test_job_solo_lleva_adjuntos_technicians_al_portal(client, sub_session, two_jobs):
    """`GET /jobs/<id>` expandía `attachments` sin podar la colección.

    `add_relationships` sólo redacta por NOMBRE DE CAMPO y `attachments` no
    estaba en RELACIONES_VETADAS_A_PORTAL, así que al sub le llegaban todos los
    adjuntos de su obra —el `logbook` interno y los sincronizados desde Podio,
    que nacen con `access_level` NULL— y cada uno con su `Link`, que es la URL
    de Cloudinary directamente descargable.
    """
    headers, _ = sub_session
    mine = two_jobs[0]
    resp = client.get(f"/jobs/{mine}", headers=headers)
    assert resp.status_code == 200
    adjuntos = resp.get_json().get("attachments") or []
    # Enumerar, no contar: el conjunto de niveles dice QUÉ se cuela.
    assert _niveles_de(adjuntos) == ["technicians"], _niveles_de(adjuntos)
    assert len(adjuntos) == 1, "el fixture siembra exactamente uno en technicians"


def test_job_del_staff_conserva_todos_los_adjuntos(client, admin_headers, two_jobs):
    """El control de la anterior: la poda no puede alcanzar al staff.

    `acotar_job_para_portal` está en el camino de las once rutas de /jobs para
    TODO el mundo; un filtro escrito un nivel de indentación más arriba dejaría
    a los administradores sin adjuntos en todo el producto.
    """
    mine = two_jobs[0]
    resp = client.get(f"/jobs/{mine}", headers=admin_headers)
    assert resp.status_code == 200
    adjuntos = resp.get_json().get("attachments") or []
    assert _niveles_de(adjuntos) == ["NULL", "logbook", "members", "technicians"]


def test_sub_lee_por_id_solo_la_carpeta_technicians(client, sub_session, two_jobs):
    """La simétrica por id: el listado y la lectura por id no pueden divergir."""
    headers, _ = sub_session
    mine = two_jobs[0]
    suffix = mine[4:]
    esperado = {"technicians": 200, "members": 403, "logbook": 403, "null": 403}
    obtenido = {}
    for nivel in esperado:
        r = client.get(f"/attachments/ATT-SCOPE-{suffix}-{nivel}", headers=headers)
        obtenido[nivel] = r.status_code
    assert obtenido == esperado, obtenido


def test_sub_lista_adjuntos_solo_technicians(client, sub_session, two_jobs):
    headers, _ = sub_session
    mine = two_jobs[0]
    resp = client.get("/attachments/", headers=headers)
    assert resp.status_code == 200
    # `add_relationships` quita la FK `ID_Jobs` y la sustituye por el objeto
    # `job` anidado, asi que hay que filtrar por el id del propio adjunto.
    suffix = mine[4:]
    del_job = [a for a in resp.get_json()
               if str(a.get("ID_Attachment", "")).startswith(f"ATT-SCOPE-{suffix}-")]
    assert _niveles_de(del_job) == ["technicians"], _niveles_de(del_job)
    assert len(del_job) == 1, [a["ID_Attachment"] for a in del_job]


def _subir(client, headers, job_id, nivel):
    data = {"entity_id": job_id,
            "file": (io.BytesIO(b"%PDF-1.4 prueba"), "prueba.pdf")}
    if nivel is not None:
        data["access_level"] = nivel
    return client.post("/attachments/upload", headers=headers, data=data,
                       content_type="multipart/form-data")


def test_sub_solo_sube_a_technicians(client, sub_session, two_jobs):
    """El sub tiene `attachment:create` GLOBAL, que cortocircuita el gate de
    carpeta: hoy pasaba las dos. La regla nueva es por ENTIDAD destino.

    Las tres negativas se comprueban además EN LA BASE: un 403 que ya hubiera
    escrito la fila sería un 403 mentiroso.
    """
    headers, _ = sub_session
    mine = two_jobs[0]
    try:
        for nivel in ("members", "logbook", None):
            r = _subir(client, headers, mine, nivel)
            assert r.status_code == 403, f"{nivel}: {r.status_code} {r.get_data(as_text=True)[:200]}"
        with get_session() as session:
            escritas = session.exec(select(Attachments).where(
                Attachments.Document_name == "prueba.pdf")).all()
            assert not escritas, [a.ID_Attachment for a in escritas]
    finally:
        # Limpiar en `finally`: si la aserción falla es justo porque SE ESCRIBIÓ,
        # y dejar la fila pone roja la corrida siguiente por otro motivo.
        with get_session() as session:
            for a in session.exec(select(Attachments).where(
                    Attachments.Document_name == "prueba.pdf")).all():
                session.delete(a)
            session.commit()


def test_staff_sigue_subiendo_a_members(client, admin_headers, two_jobs, monkeypatch):
    """El control: la regla es sólo para el portal.

    Sin esta prueba, una comprobación escrita sin `llamante_es_portal()` pasaría
    todas las de arriba y rompería la subida del personal interno.
    """
    import src.routes.Attachments as mod
    monkeypatch.setattr(mod, "upload_to_cloudinary", lambda **k: {
        "secure_url": "https://example.invalid/x.pdf", "format": "PDF",
        "public_id": "x", "resource_type": "raw", "original_name": "prueba-staff.pdf"})
    monkeypatch.setattr(mod, "get_podio_headers", lambda *a, **k: None)
    mine = two_jobs[0]
    try:
        r = _subir(client, admin_headers, mine, "members")
        assert r.status_code != 403, r.get_data(as_text=True)[:300]
    finally:
        with get_session() as session:
            for a in session.exec(select(Attachments).where(
                    Attachments.Document_name == "prueba-staff.pdf")).all():
                session.delete(a)
            session.commit()
