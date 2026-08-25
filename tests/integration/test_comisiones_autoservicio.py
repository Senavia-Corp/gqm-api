"""La pestaña Commissions de /profile: un GQM Member ve SOLO sus comisiones.

El rol GQM Member tiene `commission:*` denegado en bloque (el comodín alcanza
también a `commission:read_own`), así que /commission/member/<id> le respondía
403 y el panel pintaba la clave i18n cruda `detail.errLoad`. La ruta pasa ahora
por el mismo autoservicio que Member.get_member_by_id: entra por
`profile:update_own` y se exige que el ID sea el propio.
"""
import pytest
from decouple import config
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.MemberModel import Member


def _login(app, email):
    resp = app.test_client().post("/auth/login", json={
        "Email_Address": email, "Password": config("SEED_DEV_PASSWORD")})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    data = resp.get_json()
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user_id"]


@pytest.fixture(scope="module")
def member(app):
    return _login(app, "member-dev@senavia-test.com")


@pytest.fixture(scope="module")
def admin(app):
    return _login(app, "admin-dev@senavia-test.com")


def test_member_ve_sus_propias_comisiones(client, member):
    headers, uid = member
    resp = client.get(f"/commission/member/{uid}", headers=headers)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert isinstance(resp.get_json(), list)


def test_member_no_ve_las_de_otro(client, member):
    headers, uid = member
    with get_session() as s:
        otro = s.exec(select(Member).where(Member.ID_Member != uid)).first()
    assert otro, "se esperaba al menos otro member en develop"
    resp = client.get(f"/commission/member/{otro.ID_Member}", headers=headers)
    assert resp.status_code == 403


def test_el_autoservicio_no_abre_el_modulo_de_comisiones(client, member):
    """Solo se amplió /commission/member/<propio>: el resto sigue cerrado."""
    headers, uid = member
    for ruta in ("/commission/", "/commission/commission_table?limit=10",
                 "/commission_detail/", "/commission/excel"):
        assert client.get(ruta, headers=headers).status_code == 403, ruta


def test_full_admin_sigue_viendo_las_de_cualquiera(client, admin, member):
    headers, _ = admin
    _, uid_member = member
    resp = client.get(f"/commission/member/{uid_member}", headers=headers)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
