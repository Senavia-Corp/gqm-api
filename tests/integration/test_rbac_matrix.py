"""B2 (REG-004/006): matriz de autorización de los 4 roles contra rutas
representativas de cada grupo del RBAC. «Pasa» = status ∉ {401,403} (la ruta
puede devolver 400/404/500 por otras razones; aquí solo se prueba authz)."""
import pytest
from decouple import config

USERS = {
    "full_admin": "admin-dev@senavia-test.com",
    "gqm_member": "member-dev@senavia-test.com",
    "subcontractor": "sub-dev@senavia-test.com",
    "technical": "tech-dev@senavia-test.com",
}


@pytest.fixture(scope="module")
def tokens(app):
    client = app.test_client()
    password = config("SEED_DEV_PASSWORD")
    out = {}
    for slug, email in USERS.items():
        resp = client.post("/auth/login", json={"Email_Address": email, "Password": password})
        assert resp.status_code == 200, f"{slug}: {resp.get_data(as_text=True)[:200]}"
        out[slug] = {"Authorization": f"Bearer {resp.get_json()['access_token']}"}
    return out


# (método, path, {rol: True = pasa authz, False = 403})
MATRIX = [
    # IAM: solo Full Admin (REG-006 — aquí estaba la escalada de privilegios)
    ("POST", "/permission_role/permission/PERM-NO/role/ROL-NO",
     dict(full_admin=True, gqm_member=False, subcontractor=False, technical=False)),
    # Gestión de roles: lectura para staff, escritura solo FA
    ("GET", "/role/",
     dict(full_admin=True, gqm_member=True, subcontractor=False, technical=False)),
    ("POST", "/role/",
     dict(full_admin=True, gqm_member=False, subcontractor=False, technical=False)),
    # QBO: solo Full Admin (decisión)
    ("GET", "/qbo/connect",
     dict(full_admin=True, gqm_member=False, subcontractor=False, technical=False)),
    # Gestión de fallos de sync: admin
    ("GET", "/webhook/podio/failed_syncs",
     dict(full_admin=True, gqm_member=False, subcontractor=False, technical=False)),
    # Jobs: lectura para todos (tech vía job:read_basics); borrar SOLO Full Admin (spec RBAC)
    ("GET", "/jobs/",
     dict(full_admin=True, gqm_member=True, subcontractor=True, technical=True)),
    ("DELETE", "/jobs/NOEXISTE",
     dict(full_admin=True, gqm_member=False, subcontractor=False, technical=False)),
    # Desvincular de un job es edición (job:update): el GQM Member lo conserva
    ("DELETE", "/job_member/jobs/J-NO/members/M-NO",
     dict(full_admin=True, gqm_member=True, subcontractor=False, technical=False)),
    ("POST", "/job_technician/jobs/J-NO/technicians/T-NO",
     dict(full_admin=True, gqm_member=True, subcontractor=False, technical=False)),
    ("GET", "/jobs/subcontractor/SUBC-NO",
     dict(full_admin=True, gqm_member=True, subcontractor=False, technical=False)),
    # El Excel lleva finanzas: nunca con solo job:read_basics
    ("POST", "/jobs_excel/export",
     dict(full_admin=True, gqm_member=True, subcontractor=True, technical=False)),
    # Multiplicadores: el GQM Member los VE pero no los crea/vincula (Deny multiplier:c/u/d)
    ("GET", "/multiplier/",
     dict(full_admin=True, gqm_member=True, subcontractor=False, technical=False)),
    ("POST", "/job_multiplier/jobs/J-NO/multipliers/M-NO",
     dict(full_admin=True, gqm_member=False, subcontractor=False, technical=False)),
    # Financiero: sin finance:read el portal no lee finanzas (Fase A: sin scoping financiero)
    ("GET", "/order/job-id/NOEXISTE",
     dict(full_admin=True, gqm_member=True, subcontractor=False, technical=False)),
    ("GET", "/fdocument/",
     dict(full_admin=True, gqm_member=True, subcontractor=False, technical=False)),
    ("GET", "/estimate/",
     dict(full_admin=True, gqm_member=True, subcontractor=False, technical=False)),
    ("GET", "/metrics/financial/summary",
     dict(full_admin=True, gqm_member=True, subcontractor=False, technical=False)),
    ("POST", "/change_order/",
     dict(full_admin=True, gqm_member=True, subcontractor=False, technical=False)),
    # Members: listado (reducido a basics para el GQM Member, ver test_member_basics) y alta solo FA
    ("GET", "/member/member_table",
     dict(full_admin=True, gqm_member=True, subcontractor=False, technical=False)),
    ("POST", "/member/",
     dict(full_admin=True, gqm_member=False, subcontractor=False, technical=False)),
    ("GET", "/permission/",
     dict(full_admin=True, gqm_member=True, subcontractor=False, technical=False)),
    # Técnicos: el staff los crea; el portal no (Fase A)
    ("POST", "/technician/",
     dict(full_admin=True, gqm_member=True, subcontractor=False, technical=False)),
    # Comisiones: ningún módulo para el GQM Member (Deny commission:*, INFORME §5)
    ("GET", "/commission/",
     dict(full_admin=True, gqm_member=False, subcontractor=False, technical=False)),
    ("GET", "/commission_detail/",
     dict(full_admin=True, gqm_member=False, subcontractor=False, technical=False)),
    # Chat: exige job:read (el técnico solo tiene read_basics); el sub va por scoping
    ("GET", "/chat/job/NOEXISTE",
     dict(full_admin=True, gqm_member=True, technical=False)),
    ("POST", "/sync_revision/podio",
     dict(full_admin=True, gqm_member=False, subcontractor=False, technical=False)),
    ("POST", "/fdocument_ftransaction/fdocument/FD-NO/ftransaction/FT-NO",
     dict(full_admin=True, gqm_member=True, subcontractor=False, technical=False)),
    ("GET", "/metrics/reports/jobs",
     dict(full_admin=True, gqm_member=True, subcontractor=False, technical=False)),
    # Dashboard: staff solamente (antes /job_metrics/summary era público)
    ("GET", "/job_metrics/summary",
     dict(full_admin=True, gqm_member=True, subcontractor=False, technical=False)),
]


@pytest.mark.parametrize("method,path,expectations", MATRIX,
                         ids=[f"{m} {p}" for m, p, _ in MATRIX])
def test_rbac_matrix(client, tokens, method, path, expectations):
    for role, allowed in expectations.items():
        kwargs = {"headers": tokens[role]}
        if method in ("POST", "PATCH", "PUT"):
            kwargs["json"] = {}
        resp = client.open(path, method=method, **kwargs)
        if allowed:
            assert resp.status_code not in (401, 403), \
                f"{role} {method} {path} → {resp.status_code} (no debía ser bloqueado)"
        else:
            assert resp.status_code == 403, \
                f"{role} {method} {path} → {resp.status_code} (esperaba 403)"


def test_all_roles_require_token(client):
    assert client.get("/jobs/").status_code == 401
    assert client.get("/role/").status_code == 401


def test_member_basics_para_gqm_member(client, tokens):
    """Spec: el GQM Member no entra al módulo GQM Members, pero el panel necesita los
    nombres para los desplegables → member:read_basics devuelve lo justo."""
    r = client.get("/member/?limit=5", headers=tokens["gqm_member"])
    assert r.status_code == 200
    filas = r.get_json()["results"]
    assert filas and all(set(f) == {"ID_Member", "Member_Name", "Company_Role",
                                    "podio_item_id", "podio_profile_id"} for f in filas)
    r = client.get("/member/member_table?limit=5", headers=tokens["gqm_member"])
    assert r.status_code == 200 and "total" in r.get_json()
    assert all("Email_Address" not in f for f in r.get_json()["results"])
    # Full Admin sigue recibiendo la ficha completa
    r = client.get("/member/member_table?limit=5", headers=tokens["full_admin"])
    assert all("Email_Address" in f for f in r.get_json()["results"])


def test_member_por_id_solo_propio_para_gqm_member(client, tokens):
    yo = client.get("/auth/me", headers=tokens["gqm_member"]).get_json()["user_id"]
    otro = client.get("/auth/me", headers=tokens["full_admin"]).get_json()["user_id"]
    assert client.get(f"/member/{yo}", headers=tokens["gqm_member"]).status_code == 200
    assert client.get(f"/member/{otro}", headers=tokens["gqm_member"]).status_code == 403
    assert client.get(f"/member/{yo}", headers=tokens["full_admin"]).status_code == 200
