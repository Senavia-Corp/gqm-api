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
    # Jobs: lectura para todos (tech vía job:read_basics), delete solo staff
    ("GET", "/jobs/",
     dict(full_admin=True, gqm_member=True, subcontractor=True, technical=True)),
    ("DELETE", "/jobs/NOEXISTE",
     dict(full_admin=True, gqm_member=True, subcontractor=False, technical=False)),
    # Financiero: lectura del sub (sus orders), sin acceso del técnico
    ("GET", "/order/job-id/NOEXISTE",
     dict(full_admin=True, gqm_member=True, subcontractor=True, technical=False)),
    ("POST", "/change_order/",
     dict(full_admin=True, gqm_member=True, subcontractor=False, technical=False)),
    # Members: staff solamente
    ("GET", "/member/member_table",
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
