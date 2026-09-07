"""O-01 · La política de contraseñas se impone en SERVIDOR.

Antes del arreglo, medido: `POST /technician/` aceptaba `"1"`, `"abc"`,
`"password"` y `"12345678"` — las cuatro devolvían 201 y la fila quedaba
escrita con esa contraseña. No había longitud mínima, ni lista de prohibidas,
ni complejidad, en ninguna de las tres puertas.

Importa ahora y no dentro de seis meses porque el alta del portal son 432
subcontratistas con contraseña escrita a mano por un administrador.

Estas pruebas cubrían un hueco real del arnés: `validar_password` no tenía NI
UNA prueba, así que borrarla de todas las rutas habría dejado la suite entera
en verde.

La comprobación NO es sólo el 400: después de cada rechazo se RELEE la BD para
confirmar que no se escribió nada. Un 400 con la fila creada sería peor que un
201 honesto.
"""
import uuid

import pytest
from decouple import config
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.MemberModel import Member
from src.models.SubcontractorModel import Subcontractor
from src.models.TechnicianModel import Technician
from src.utils.middleware.auth.password_hashing import verify_password

# Las cuatro que el informe midió como aceptadas, más los bordes de cada regla.
DEBILES = [
    ("1", "un solo carácter"),
    ("abc", "tres letras"),
    ("password", "está en la lista de prohibidas"),
    ("12345678", "prohibida y además corta"),
    ("Abcdefgh1", "9 caracteres: uno por debajo del mínimo"),
    ("abcdefghij", "10 pero una sola clase de carácter"),
    ("abcdefghij1", "11 pero sólo dos clases"),
    ("aaaaaaaaaaaa", "un único carácter repetido"),
    ("   ", "sólo espacios"),
]

# Cumple las cuatro reglas: 10+, tres clases, no prohibida, no repetida.
FUERTE = "Cl4ve-Buena!2026"


def _id_nuevo(prefijo):
    return f"{prefijo}{uuid.uuid4().int % 90000 + 10000}"


@pytest.mark.parametrize("password,motivo", DEBILES, ids=[m for _, m in DEBILES])
def test_alta_de_tecnico_rechaza_password_debil(client, admin_headers, password, motivo):
    tid = _id_nuevo("TECP")
    email = f"{tid.lower()}@senavia-test.com"
    resp = client.post("/technician/", headers=admin_headers, json={
        "ID_Technician": tid, "Name": "Política", "Email_Address": email,
        "Password": password})
    assert resp.status_code == 400, (
        f"«{password}» ({motivo}) entró con {resp.status_code}: "
        f"{resp.get_data(as_text=True)[:200]}")

    # La respuesta HTTP no es la verdad: se relee la BD. Se busca por CORREO y
    # no por el id que mandamos, porque `POST /technician/` lo REESCRIBE con
    # `generate_custom_id`: preguntar por el id enviado no encontraría nada
    # nunca y esta aserción no podría fallar.
    with get_session() as s:
        fila = s.exec(select(Technician).where(Technician.Email_Address == email)).first()
    assert fila is None, f"400 devuelto pero la fila de {email} se escribió igual"


@pytest.mark.parametrize("password,motivo", DEBILES, ids=[m for _, m in DEBILES])
def test_alta_de_member_rechaza_password_debil(client, admin_headers, password, motivo):
    mid = _id_nuevo("MEMP")
    email = f"{mid.lower()}@senavia-test.com"
    resp = client.post("/member/", headers=admin_headers, json={
        "ID_Member": mid, "Member_Name": "Política", "Email_Address": email,
        "Password": password})
    assert resp.status_code == 400, (
        f"«{password}» ({motivo}) entró con {resp.status_code}: "
        f"{resp.get_data(as_text=True)[:200]}")
    # Por correo, no por el id enviado: el servidor lo reescribe (ver arriba).
    with get_session() as s:
        fila = s.exec(select(Member).where(Member.Email_Address == email)).first()
    assert fila is None, f"400 devuelto pero la fila de {email} se escribió igual"


@pytest.fixture()
def tecnico_desechable(client, admin_headers):
    """Un técnico creado con contraseña buena, para probar la puerta del PATCH."""
    tid = _id_nuevo("TECU")
    email = f"{tid.lower()}@senavia-test.com"
    resp = client.post("/technician/", headers=admin_headers, json={
        "ID_Technician": tid, "Name": "Política Update", "Email_Address": email,
        "Password": FUERTE})
    assert resp.status_code == 201, resp.get_data(as_text=True)[:300]
    # El id de verdad es el que devuelve el API, no el que mandamos.
    tid = (resp.get_json() or {}).get("ID_Technician") or tid
    yield tid
    with get_session() as s:
        fila = s.exec(select(Technician).where(Technician.ID_Technician == tid)).first()
        if fila:
            s.delete(fila)
            s.commit()


def test_la_puerta_del_update_tambien_valida(client, admin_headers, tecnico_desechable):
    """El alta no es la única puerta: `PATCH` reescribe la contraseña igual."""
    tid = tecnico_desechable
    with get_session() as s:
        hash_antes = s.exec(
            select(Technician).where(Technician.ID_Technician == tid)).first().Password

    resp = client.patch(f"/technician/{tid}", headers=admin_headers,
                        json={"Password": "12345678"})
    assert resp.status_code == 400, resp.get_data(as_text=True)[:200]

    with get_session() as s:
        fila = s.exec(select(Technician).where(Technician.ID_Technician == tid)).first()
    assert fila.Password == hash_antes, "la contraseña débil se escribió pese al 400"
    assert verify_password(FUERTE, fila.Password), "la contraseña buena dejó de valer"


def test_una_password_que_cumple_si_entra(client, admin_headers):
    """Sin esto la política podría estar rechazándolo TODO y las pruebas de
    arriba seguirían en verde: una puerta cerrada con ladrillos también da 400."""
    tid = _id_nuevo("TECOK")
    email = f"{tid.lower()}@senavia-test.com"
    resp = client.post("/technician/", headers=admin_headers, json={
        "ID_Technician": tid, "Name": "Política OK", "Email_Address": email,
        "Password": FUERTE})
    assert resp.status_code == 201, resp.get_data(as_text=True)[:300]
    try:
        with get_session() as s:
            fila = s.exec(select(Technician).where(Technician.Email_Address == email)).first()
        assert fila is not None
        # Y se guarda HASHEADA, no en claro.
        assert fila.Password != FUERTE, "la contraseña se guardó en claro"
        assert verify_password(FUERTE, fila.Password)
    finally:
        with get_session() as s:
            fila = s.exec(select(Technician).where(Technician.Email_Address == email)).first()
            if fila:
                s.delete(fila)
                s.commit()


def test_reset_password_es_la_tercera_puerta(client, admin_headers, tecnico_desechable):
    """`/auth/reset-password` es la única puerta que NO exige estar autenticado:
    la más fácil de usar y la que menos se mira. Antes sólo miraba `len < 8`, así
    que «12345678» —que está en la lista de prohibidas— entraba tal cual."""
    from src.routes.Login_auth import _reset_serializer

    tid = tecnico_desechable
    with get_session() as s:
        fila = s.exec(select(Technician).where(Technician.ID_Technician == tid)).first()
        token = _reset_serializer().dumps(
            {"uid": tid, "ut": "technician", "ph": fila.Password[-12:]})
        hash_antes = fila.Password

    resp = client.post("/auth/reset-password",
                       json={"token": token, "Password": "12345678"})
    assert resp.status_code == 400, resp.get_data(as_text=True)[:200]
    with get_session() as s:
        fila = s.exec(select(Technician).where(Technician.ID_Technician == tid)).first()
    assert fila.Password == hash_antes, "la contraseña débil se escribió pese al 400"

    # Y el mismo token, con una contraseña que cumple, sí funciona: así se
    # distingue «la política rechazó» de «el token no valía».
    resp = client.post("/auth/reset-password",
                       json={"token": token, "Password": "Otra-Cl4ve!2026"})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
    with get_session() as s:
        fila = s.exec(select(Technician).where(Technician.ID_Technician == tid)).first()
    assert verify_password("Otra-Cl4ve!2026", fila.Password)


# ── Las puertas que faltaban ────────────────────────────────────────────────
#
# La cabecera de este fichero decía «las tres puertas» y la revisión adversarial
# lo midió: `validar_password` se llama en SIETE sitios, y este fichero sólo
# ejercitaba cuatro. Los tres que faltaban eran `POST /subcontractors/`,
# `PATCH /subcontractors/<id>` y `PATCH /member/<id>` — y el del subcontratista
# es justo el principal que esta auditoría existe para encender.
#
# Medido por la revisión: con `pass` en lugar de las dos llamadas de
# `Subcontractor.py`, `POST /subcontractors/` aceptaba `Password="1"`, la fila
# quedaba escrita, y `scripts/verificar_portal.sh` seguía imprimiendo
# «✅ VERDE — los 5 bloques pasan».

@pytest.mark.parametrize("password,motivo", DEBILES, ids=[m for _, m in DEBILES])
def test_alta_de_subcontratista_rechaza_password_debil(client, admin_headers, password, motivo):
    sid = _id_nuevo("SUBP")
    email = f"{sid.lower()}@senavia-test.com"
    resp = client.post("/subcontractors/", headers=admin_headers, json={
        "ID_Subcontractor": sid, "Name": "Política", "Email_Address": email,
        "Password": password})
    # Con limpieza en `finally`: si la validación se rompe, esta prueba ESCRIBE
    # la fila, y como el índice único de `e9c1correo` no deja repetir el correo,
    # la corrida siguiente fallaría con un 409 en vez de con el 400 que se está
    # midiendo. Pasó al sabotear las dos puertas de Subcontractor.py: quedaron
    # nueve subcontratistas basura en la base.
    try:
        assert resp.status_code == 400, (
            f"«{password}» ({motivo}) entró con {resp.status_code}: "
            f"{resp.get_data(as_text=True)[:200]}")
        # Por correo: el servidor reescribe el id enviado (mismo motivo que arriba).
        with get_session() as s:
            fila = s.exec(select(Subcontractor).where(
                Subcontractor.Email_Address == email)).first()
        assert fila is None, f"400 devuelto pero la fila de {email} se escribió igual"
    finally:
        with get_session() as s:
            for fila in s.exec(select(Subcontractor).where(
                    Subcontractor.Email_Address == email)).all():
                s.delete(fila)
            s.commit()


@pytest.fixture()
def subcontratista_desechable(client, admin_headers):
    sid = _id_nuevo("SUBU")
    email = f"{sid.lower()}@senavia-test.com"
    resp = client.post("/subcontractors/", headers=admin_headers, json={
        "ID_Subcontractor": sid, "Name": "Política Update",
        "Email_Address": email, "Password": FUERTE})
    assert resp.status_code == 201, resp.get_data(as_text=True)[:300]
    sid = (resp.get_json() or {}).get("ID_Subcontractor") or sid
    yield sid
    with get_session() as s:
        fila = s.exec(select(Subcontractor).where(
            Subcontractor.ID_Subcontractor == sid)).first()
        if fila:
            s.delete(fila)
            s.commit()


def test_el_update_del_subcontratista_tambien_valida(client, admin_headers,
                                                     subcontratista_desechable):
    """`PATCH /subcontractors/<id>` es alcanzable por el PROPIO subcontratista
    vía `profile:update_own`: `self_profile_guard` deja pasar `Password` porque
    no es un campo privilegiado. Es decir, la puerta por la que un sub se
    cambia su propia contraseña."""
    sid = subcontratista_desechable
    with get_session() as s:
        antes = s.exec(select(Subcontractor).where(
            Subcontractor.ID_Subcontractor == sid)).first().Password

    resp = client.patch(f"/subcontractors/{sid}", headers=admin_headers,
                        json={"Password": "12345678"})
    assert resp.status_code == 400, resp.get_data(as_text=True)[:200]

    with get_session() as s:
        despues = s.exec(select(Subcontractor).where(
            Subcontractor.ID_Subcontractor == sid)).first().Password
    assert despues == antes, "la contraseña débil se escribió pese al 400"


def test_el_update_del_member_tambien_valida(client, admin_headers):
    """La cuarta que tampoco estaba: `PATCH /member/<id>` (Member.py:283)."""
    mid = _id_nuevo("MEMU")
    email = f"{mid.lower()}@senavia-test.com"
    alta = client.post("/member/", headers=admin_headers, json={
        "ID_Member": mid, "Member_Name": "Política Update",
        "Email_Address": email, "Password": FUERTE})
    assert alta.status_code == 201, alta.get_data(as_text=True)[:300]
    mid = (alta.get_json() or {}).get("ID_Member") or mid
    try:
        with get_session() as s:
            antes = s.exec(select(Member).where(Member.ID_Member == mid)).first().Password
        resp = client.patch(f"/member/{mid}", headers=admin_headers,
                            json={"Password": "12345678"})
        assert resp.status_code == 400, resp.get_data(as_text=True)[:200]
        with get_session() as s:
            despues = s.exec(select(Member).where(Member.ID_Member == mid)).first().Password
        assert despues == antes, "la contraseña débil se escribió pese al 400"
    finally:
        with get_session() as s:
            fila = s.exec(select(Member).where(Member.ID_Member == mid)).first()
            if fila:
                s.delete(fila)
                s.commit()


# ── La prueba que impide que esto se repita ────────────────────────────────

# Cada llamada a `validar_password` en el código de rutas, identificada por
# (módulo, función que la contiene) — estable aunque se muevan las líneas — y
# la prueba de ESTE fichero que la ejercita. Añadir una puerta nueva sin
# cubrirla pone rojo `test_toda_puerta_de_password_tiene_prueba`.
PUERTAS_CUBIERTAS = {
    # `create_techician` va sin la «n»: es una errata en el nombre de la
    # función de `src/routes/Technician.py:134`, y como Flask usa el nombre de
    # la función como endpoint, corregirla cambiaría el endpoint. Se deja y se
    # apunta tal cual: esta prueba la encontró al fallar contra mi suposición.
    ("Technician.py", "create_techician"):      "test_alta_de_tecnico_rechaza_password_debil",
    ("Technician.py", "update_technician"):     "test_la_puerta_del_update_tambien_valida",
    ("Member.py", "create_member"):             "test_alta_de_member_rechaza_password_debil",
    ("Member.py", "update_member"):             "test_el_update_del_member_tambien_valida",
    ("Subcontractor.py", "create_subcontractor"): "test_alta_de_subcontratista_rechaza_password_debil",
    ("Subcontractor.py", "update_subcontractor"): "test_el_update_del_subcontratista_tambien_valida",
    ("Login_auth.py", "reset_password"):        "test_reset_password_es_la_tercera_puerta",
}


def _puertas_en_el_codigo():
    """(módulo, función) de cada llamada real a `validar_password` en src/routes.

    Por AST y no por grep: así no cuentan ni el `import` ni las menciones en
    comentarios o docstrings, que es lo que haría que esta prueba mintiera.
    """
    import ast
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2] / "src" / "routes"
    encontradas = set()
    for fichero in raiz.rglob("*.py"):
        arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for hijo in ast.walk(nodo):
                if (isinstance(hijo, ast.Call)
                        and isinstance(hijo.func, ast.Name)
                        and hijo.func.id == "validar_password"):
                    encontradas.add((fichero.name, nodo.name))
    return encontradas


def test_toda_puerta_de_password_tiene_prueba():
    """El hueco que la revisión encontró, convertido en prueba.

    Este fichero decía cubrir «las tres puertas» cuando `validar_password` se
    llamaba en siete sitios: los dos del subcontratista y el `PATCH` del member
    no tenían ninguna, y borrarlos dejaba la suite —y el veredicto de
    `verificar_portal.sh`— en verde.

    Contar no vale: se ENUMERA y se comparan los conjuntos, para que el mensaje
    diga exactamente cuál falta.
    """
    en_el_codigo = _puertas_en_el_codigo()
    declaradas = set(PUERTAS_CUBIERTAS)

    sin_prueba = en_el_codigo - declaradas
    assert not sin_prueba, (
        "hay puertas que validan contraseñas y no tiene prueba ninguna:\n  "
        + "\n  ".join(f"{m}::{f}" for m, f in sorted(sin_prueba))
        + "\nAñade la prueba y apúntala en PUERTAS_CUBIERTAS.")

    fantasmas = declaradas - en_el_codigo
    assert not fantasmas, (
        "PUERTAS_CUBIERTAS declara puertas que ya no existen en el código "
        "(¿se quitó la validación?):\n  "
        + "\n  ".join(f"{m}::{f}" for m, f in sorted(fantasmas)))

    # Y que las pruebas nombradas existan de verdad en este módulo.
    import sys
    faltan = [t for t in PUERTAS_CUBIERTAS.values()
              if not hasattr(sys.modules[__name__], t)]
    assert not faltan, f"PUERTAS_CUBIERTAS nombra pruebas inexistentes: {faltan}"
