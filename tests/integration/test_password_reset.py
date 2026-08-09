"""REG-047/048/049: forgot → email con link → reset → login; un solo uso."""
import uuid

import pytest
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.MemberModel import Member
from src.utils.middleware.auth.password_hashing import hash_password


@pytest.fixture()
def disposable_member():
    suffix = uuid.uuid4().int % 90000 + 10000
    email = f"reset-test-{suffix}@senavia-test.com"
    with get_session() as session:
        member = Member(
            ID_Member=f"MEMT{suffix}", Member_Name="Reset Test",
            Email_Address=email, Password=hash_password("vieja-clave-123"),
        )
        session.add(member)
        session.commit()
    yield email
    with get_session() as session:
        member = session.exec(select(Member).where(Member.Email_Address == email)).first()
        if member:
            session.delete(member)
            session.commit()


def test_full_reset_flow_single_use(client, disposable_member, monkeypatch):
    email = disposable_member
    captured = {}
    monkeypatch.setattr(
        "src.services.email_service.send_password_reset",
        lambda to, url: captured.update(to=to, url=url) or True,
    )

    # 1. forgot → siempre 200 y el correo sale con el link
    resp = client.post("/auth/forgot-password", json={"Email_Address": email})
    assert resp.status_code == 200
    assert captured["to"] == email
    token = captured["url"].split("token=")[1]

    # 2. email inexistente → mismo 200, sin correo
    captured.clear()
    resp = client.post("/auth/forgot-password", json={"Email_Address": "nadie@senavia-test.com"})
    assert resp.status_code == 200
    assert not captured

    # 3. reset con el token
    resp = client.post("/auth/reset-password",
                       json={"token": token, "Password": "nueva-clave-456"})
    assert resp.status_code == 200

    # 4. login con la nueva; la vieja ya no sirve
    ok = client.post("/auth/login", json={"Email_Address": email, "Password": "nueva-clave-456"})
    assert ok.status_code == 200
    bad = client.post("/auth/login", json={"Email_Address": email, "Password": "vieja-clave-123"})
    assert bad.status_code == 401

    # 5. el token es de un solo uso
    reuse = client.post("/auth/reset-password",
                        json={"token": token, "Password": "otra-mas-789"})
    assert reuse.status_code == 400


def test_reset_rejects_garbage_token(client):
    resp = client.post("/auth/reset-password",
                       json={"token": "basura", "Password": "loquesea123"})
    assert resp.status_code == 400


def test_login_rate_limit_429(client):
    """REG-051: 6º intento en la ventana → 429."""
    email = "ratelimit-test@senavia-test.com"
    for _ in range(5):
        resp = client.post("/auth/login", json={"Email_Address": email, "Password": "mala"})
        assert resp.status_code == 401
    resp = client.post("/auth/login", json={"Email_Address": email, "Password": "mala"})
    assert resp.status_code == 429
