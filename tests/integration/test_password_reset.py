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
        lambda to, enlaces: captured.update(to=to, enlaces=list(enlaces)) or True,
    )

    # 1. forgot → siempre 200 y el correo sale con el link
    resp = client.post("/auth/forgot-password", json={"Email_Address": email})
    assert resp.status_code == 200
    assert captured["to"] == email
    token = captured["enlaces"][0][1].split("token=")[1]

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
    envios = []
    monkeypatch.setattr(
        "src.services.email_service.send_password_reset",
        lambda to, enlaces: envios.append({"to": to, "enlaces": list(enlaces)}) or True,
    )
    resp = client.post("/auth/forgot-password", json={"Email_Address": email})
    assert resp.status_code == 200

    # UN SOLO envio, con todos los enlaces dentro. Uno por principal costaba una
    # conexion SMTP por cuenta y hacia que el tiempo de respuesta delatara
    # CUANTAS cuentas tiene la direccion: el 200 constante no oculta nada al
    # reloj si el trabajo escala con N.
    assert len(envios) == 1, f"salieron {len(envios)} correos; debe salir uno"
    assert envios[0]["to"] == email

    # Se ENUMERA, no se cuenta: «2 == 2» taparia un ausente compensado.
    tipos = sorted(tipo for tipo, _ in envios[0]["enlaces"])
    assert tipos == ["member", "technician"], (
        f"la recuperacion solo alcanzo a {tipos}; el resto queda sin salida"
    )

    # Y los enlaces son DISTINTOS: dos con el mismo token reiniciarian la misma
    # cuenta y el otro principal seguiria bloqueado.
    tokens = {url.split("token=")[1] for _, url in envios[0]["enlaces"]}
    assert len(tokens) == 2, "los dos enlaces apuntan a la misma cuenta"

    # Cada token reinicia SU cuenta, no la del otro.
    por_tipo = {tipo: url.split("token=")[1] for tipo, url in envios[0]["enlaces"]}
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



def test_el_cupo_del_limitador_no_se_reinicia_con_un_espacio(client, monkeypatch):
    """O-05 bis · Un espacio delante del correo abría un cupo nuevo.

    `_client_key` normaliza con `.strip().lower()`, pero la llamada era
    `_client_key(f"forgot|{email}")`: el strip recorta los extremos de
    `"forgot| ana@x.com"`, que no tiene ninguno, y el espacio interior
    sobrevive. Medido con la función en la mano:

        _client_key("forgot|ana@x.com")  -> 1.2.3.4|forgot|ana@x.com
        _client_key("forgot| ana@x.com") -> 1.2.3.4|forgot| ana@x.com

    Dos cupos para el mismo usuario. El login, que pasa el correo suelto, sí
    estaba bien — por eso hacía falta mirar ESTA ruta y no dar por hecho que
    la protección del login la cubría.
    """
    cap = _env("LOGIN_RATE_MAX_ATTEMPTS", default=5, cast=int)
    correo = f"cupo-{uuid.uuid4().hex[:12]}@senavia-test.com"
    monkeypatch.setattr("src.services.email_service.send_password_reset",
                        lambda to, enlaces: True)

    # Se gasta el cupo con la forma limpia.
    for _ in range(cap):
        assert client.post("/auth/forgot-password",
                           json={"Email_Address": correo}).status_code == 200
    assert client.post("/auth/forgot-password",
                       json={"Email_Address": correo}).status_code == 429

    # Y las variantes que la BÚSQUEDA considera el mismo usuario tienen que
    # encontrarse el mismo cupo gastado. Se ENUMERAN todas, no se prueba una:
    # con un solo caso, la que se dejara fuera seguiría siendo la puerta.
    for variante in (f" {correo}", f"{correo} ", f"\t{correo}", correo.upper(),
                     f"  {correo.upper()}  "):
        r = client.post("/auth/forgot-password", json={"Email_Address": variante})
        assert r.status_code == 429, (
            f"«{variante!r}» abrió un cupo nuevo: {r.status_code}")


def test_un_correo_guardado_con_espacios_no_es_una_cuenta_muda(client, monkeypatch):
    """O-05 bis · La búsqueda normalizaba la ENTRADA pero no la COLUMNA.

    Una fila importada como 'ana@x.com ' —lo que la propia migración e9c1correo
    advierte que pasa en una importación de 432 filas de Podio— existía, tenía
    contraseña, y ni podía entrar ni podía recuperarla: 401 con la contraseña
    buena y 200 sin correo. La cuenta muda exacta que O-05 venía a quitar.
    """
    from src.models.TechnicianModel import Technician
    suf = uuid.uuid4().int % 90000 + 10000
    limpio = f"espacios-{suf}@senavia-test.com"
    clave = "Cl4ve-Con-Espacios!2026"
    with get_session() as s:
        s.add(Technician(ID_Technician=f"TECE{suf}", Name="Espacios",
                         Email_Address=f"  {limpio}\t", Password=hash_password(clave)))
        s.commit()
    try:
        # Entra escribiendo el correo limpio.
        r = client.post("/auth/login", json={"Email_Address": limpio, "Password": clave})
        assert r.status_code == 200, r.get_data(as_text=True)[:200]
        assert r.get_json()["user_type"] == "technician"

        # Y la recuperación lo alcanza.
        envios = []
        monkeypatch.setattr("src.services.email_service.send_password_reset",
                            lambda to, enlaces: envios.append(list(enlaces)) or True)
        assert client.post("/auth/forgot-password",
                           json={"Email_Address": limpio}).status_code == 200
        assert envios, "la cuenta con espacios guardados sigue sin recibir enlace"
        assert [tipo for tipo, _ in envios[0]] == ["technician"]
    finally:
        with get_session() as s:
            for f in s.exec(select(Technician).where(
                    Technician.ID_Technician == f"TECE{suf}")).all():
                s.delete(f)
            s.commit()
