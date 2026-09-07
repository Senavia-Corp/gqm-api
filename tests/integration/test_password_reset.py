"""REG-047/048/049: forgot → email con link → reset → login; un solo uso."""
import uuid

import pytest
from decouple import config as _env
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
        lambda to, url, tipo_de_cuenta=None: captured.update(to=to, url=url) or True,
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
    """REG-051: el intento que pasa el cap configurado → 429.

    El cap se lee del entorno (LOGIN_RATE_MAX_ATTEMPTS, por defecto 5) en vez de
    estar fijo en 5/6: asi el test sigue probando el limitador aunque se suba el
    valor en dev, en vez de romperse o —peor— quedarse verde sin comprobar nada.
    """
    cap = _env("LOGIN_RATE_MAX_ATTEMPTS", default=5, cast=int)
    # Correo NUEVO en cada corrida: el limitador cuenta en la BD (tabla
    # `login_attempt`), no en memoria, asi que con una direccion fija el cupo
    # seguia gastado al volver a lanzar el fichero dentro de la misma ventana
    # de 60 s y el primer intento —que debe dar 401— daba 429. El test no
    # podia correrse dos veces seguidas, que es justo lo que se hace al
    # iterar sobre un arreglo.
    email = f"ratelimit-test-{uuid.uuid4().hex[:12]}@senavia-test.com"
    for _ in range(cap):
        resp = client.post("/auth/login", json={"Email_Address": email, "Password": "mala"})
        assert resp.status_code == 401
    resp = client.post("/auth/login", json={"Email_Address": email, "Password": "mala"})
    assert resp.status_code == 429


@pytest.fixture()
def choque_member_tecnico():
    """Un member y un technician con EL MISMO correo.

    No es un montaje artificial: los indices unicos de correo (migracion
    e9c1correo) son por tabla, y en produccion conviven 432 subcontratistas
    importados de Podio con members y technicians sin que nadie garantice
    que una direccion no aparece en dos de esas tablas.
    """
    from src.models.TechnicianModel import Technician
    suffix = uuid.uuid4().int % 90000 + 10000
    email = f"choque-{suffix}@senavia-test.com"
    with get_session() as session:
        session.add(Member(
            ID_Member=f"MEMC{suffix}", Member_Name="Choque Member",
            Email_Address=email, Password=hash_password("Miembro-Cl4ve!2026"),
        ))
        session.add(Technician(
            ID_Technician=f"TECC{suffix}", Name="Choque Tecnico",
            Email_Address=email, Password=hash_password("Tecnico-Cl4ve!2026"),
        ))
        session.commit()
    yield email
    with get_session() as session:
        for Model in (Member, Technician):
            for row in session.exec(
                select(Model).where(Model.Email_Address == email)
            ).all():
                session.delete(row)
        session.commit()


def test_forgot_alcanza_a_todos_los_principales_del_correo(
        client, choque_member_tecnico, monkeypatch):
    """O-05: la puerta de recuperacion debe llegar tan lejos como la de entrada.

    `/auth/login` prueba la contrasena en las tres tablas y sigue buscando si
    no casa, asi que member y technician entran los dos. `forgot-password`
    devolvia el PRIMER acierto por orden de tabla y mandaba el enlace solo al
    member: el tecnico no podia recuperar su contrasena jamas, y con el 200
    constante de la respuesta nadie podia notarlo.
    """
    email = choque_member_tecnico

    # La puerta de ENTRADA alcanza a los dos: eso fija el listón.
    entran = {}
    for etiqueta, pw in (("member", "Miembro-Cl4ve!2026"),
                         ("technician", "Tecnico-Cl4ve!2026")):
        r = client.post("/auth/login", json={"Email_Address": email, "Password": pw})
        assert r.status_code == 200, f"{etiqueta}: {r.get_data(as_text=True)[:200]}"
        entran[etiqueta] = r.get_json()["user_type"]
    assert entran == {"member": "member", "technician": "technician"}

    # La puerta de RECUPERACION tiene que alcanzar a los mismos.
    enviados = []
    monkeypatch.setattr(
        "src.services.email_service.send_password_reset",
        lambda to, url, tipo_de_cuenta=None:
            enviados.append({"to": to, "url": url, "tipo": tipo_de_cuenta}) or True,
    )
    resp = client.post("/auth/forgot-password", json={"Email_Address": email})
    assert resp.status_code == 200

    # Se ENUMERA, no se cuenta: «2 == 2» taparia un ausente compensado.
    tipos = sorted(e["tipo"] for e in enviados)
    assert tipos == ["member", "technician"], (
        f"la recuperacion solo alcanzo a {tipos}; el resto queda sin salida"
    )
    assert {e["to"] for e in enviados} == {email}

    # Y los enlaces son DISTINTOS: dos correos con el mismo token reiniciarian
    # la misma cuenta y el otro principal seguiria bloqueado.
    tokens = {e["url"].split("token=")[1] for e in enviados}
    assert len(tokens) == 2, "los dos enlaces apuntan a la misma cuenta"

    # Cada token reinicia SU cuenta, no la del otro.
    por_tipo = {e["tipo"]: e["url"].split("token=")[1] for e in enviados}
    r = client.post("/auth/reset-password",
                    json={"token": por_tipo["technician"], "Password": "Nueva-Tecnico!2026"})
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    # el tecnico entra con la nueva
    ok = client.post("/auth/login",
                     json={"Email_Address": email, "Password": "Nueva-Tecnico!2026"})
    assert ok.status_code == 200 and ok.get_json()["user_type"] == "technician"
    # y el member conserva la suya (el reinicio no se llevo por delante al otro)
    intacto = client.post("/auth/login",
                          json={"Email_Address": email, "Password": "Miembro-Cl4ve!2026"})
    assert intacto.status_code == 200 and intacto.get_json()["user_type"] == "member"
