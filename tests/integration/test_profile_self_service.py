"""Review final Fase 1 (ALTO): autoservicio de perfil.

Sin {resource}:update, profile:update_own permite editar SOLO el propio
registro y sin campos privilegiados (ID_Role/Active)."""
import pytest
from decouple import config
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.MemberModel import Member
from src.models.SubcontractorModel import Subcontractor


def _login(app, email):
    resp = app.test_client().post("/auth/login", json={
        "Email_Address": email, "Password": config("SEED_DEV_PASSWORD")})
    assert resp.status_code == 200
    data = resp.get_json()
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user_id"]


@pytest.fixture(scope="module")
def member(app):
    return _login(app, "member-dev@senavia-test.com")


@pytest.fixture(scope="module")
def sub(app):
    return _login(app, "sub-dev@senavia-test.com")


def test_member_can_edit_own_profile_but_not_role(client, member):
    headers, uid = member
    with get_session() as s:
        role_before = s.get(Member, uid).ID_Role
    resp = client.patch(f"/member/{uid}", headers=headers, json={
        "Phone_Number": "555-0100", "ID_Role": "ROL-HACK"})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    with get_session() as s:
        row = s.get(Member, uid)
        assert row.Phone_Number == "555-0100"
        assert row.ID_Role == role_before  # privilegiado: filtrado, no aplicado


def test_member_cannot_edit_other_member(client, member):
    headers, uid = member
    with get_session() as s:
        other = s.exec(select(Member).where(Member.ID_Member != uid)).first()
    assert other, "se esperaba al menos otro member en develop"
    resp = client.patch(f"/member/{other.ID_Member}", headers=headers,
                        json={"Phone_Number": "555-0199"})
    assert resp.status_code == 403


def test_sub_can_edit_own_profile(client, sub):
    headers, uid = sub
    resp = client.patch(f"/subcontractors/{uid}", headers=headers,
                        json={"Phone_Number": "555-0101"})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]


def test_sub_cannot_edit_other_sub(client, sub):
    headers, uid = sub
    with get_session() as s:
        other = s.exec(select(Subcontractor).where(
            Subcontractor.ID_Subcontractor != uid)).first()
    assert other, "se esperaba al menos otro subcontractor en develop"
    resp = client.patch(f"/subcontractors/{other.ID_Subcontractor}",
                        headers=headers, json={"Phone_Number": "555-0199"})
    assert resp.status_code == 403
