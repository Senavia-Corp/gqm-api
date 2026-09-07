"""O-02 · Un correo, un principal: los índices únicos parciales de e9c1correo.

El correo es la credencial de acceso: `/auth/login` busca por él. Con dos filas
de la misma tabla compartiendo dirección, quién entra lo decide el orden que
devuelva Postgres — es decir, nadie. Y con 432 subcontratistas importados de
Podio, donde la capitalización del correo no la controla nadie, «Sub@x.com» y
«sub@x.com » (con espacio) eran dos filas distintas para la BD y la MISMA para
el login, que normaliza con `strip().lower()`.

La migración `e9c1correo` crea tres índices únicos parciales sobre
`lower(btrim("Email_Address"))`, con predicado
`WHERE "Email_Address" IS NOT NULL AND btrim("Email_Address") <> ''`.

Estas pruebas cubrían otro hueco del arnés: la migración no tenía NINGUNA, así
que borrarla habría dejado la suite en verde.

Se ejercita la BD directamente, no el API: lo que se afirma aquí es la
restricción de integridad, que es la que sigue valiendo aunque mañana aparezca
otra ruta de alta o una importación masiva que no pase por las rutas.
"""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.MemberModel import Member
from src.models.SubcontractorModel import Subcontractor
from src.models.TechnicianModel import Technician

# `Password` es NOT NULL en member y technician: sin esto el INSERT falla por
# otra razón y `pytest.raises(IntegrityError)` se pondría verde por el motivo
# equivocado — que es justo lo que pasó la primera vez que se corrieron.
_CLAVE = "Cl4ve-Buena!2026"

# (Modelo, campo de id, prefijo, índice esperado, campos obligatorios extra)
TABLAS = [
    pytest.param(Member, "ID_Member", "MEMQ", "ux_member_email_lower",
                 {"Member_Name": "Correo Único", "Password": _CLAVE}, id="member"),
    pytest.param(Technician, "ID_Technician", "TECQ", "ux_technician_email_lower",
                 {"Name": "Correo Único", "Password": _CLAVE}, id="technician"),
    pytest.param(Subcontractor, "ID_Subcontractor", "SUBQ", "ux_subcontractor_email_lower",
                 {"Name": "Correo Único", "Password": _CLAVE}, id="subcontractor"),
]


def _es_choque_de_correo(excinfo, indice):
    """Que el error sea EL del índice de correo, no cualquier IntegrityError.

    `pytest.raises(IntegrityError)` acepta también un NOT NULL o una clave
    ajena: se pondría verde sin que el índice existiera siquiera.
    """
    texto = str(excinfo.value)
    assert indice in texto, (
        f"saltó una IntegrityError distinta de {indice}: {texto[:300]}")


def _sufijo():
    return uuid.uuid4().int % 90000 + 10000


def _limpiar(Model, campo_id, ids):
    with get_session() as s:
        for i in ids:
            fila = s.exec(select(Model).where(getattr(Model, campo_id) == i)).first()
            if fila:
                s.delete(fila)
        s.commit()


@pytest.mark.parametrize("Model,campo_id,prefijo,indice,extra", TABLAS)
def test_no_se_puede_repetir_el_correo(Model, campo_id, prefijo, indice, extra):
    n = _sufijo()
    correo = f"unico-{n}@senavia-test.com"
    a, b = f"{prefijo}A{n}", f"{prefijo}B{n}"
    try:
        with get_session() as s:
            s.add(Model(**{campo_id: a, "Email_Address": correo, **extra}))
            s.commit()

        with pytest.raises(IntegrityError) as fallo:
            with get_session() as s:
                s.add(Model(**{campo_id: b, "Email_Address": correo, **extra}))
                s.commit()
        _es_choque_de_correo(fallo, indice)

        # Se ENUMERA lo que quedó: «hubo un error» no prueba que no se escribiera.
        with get_session() as s:
            filas = sorted(
                getattr(f, campo_id)
                for f in s.exec(select(Model).where(Model.Email_Address == correo)).all())
        assert filas == [a], f"quedaron {filas} con el mismo correo"
    finally:
        _limpiar(Model, campo_id, [a, b])


@pytest.mark.parametrize("Model,campo_id,prefijo,indice,extra", TABLAS)
@pytest.mark.parametrize("variante", ["MAYUSCULAS", "  espacios  ", "MeZcLaDo"],
                         ids=["mayúsculas", "espacios alrededor", "mezcla"])
def test_el_duplicado_se_detecta_normalizado(Model, campo_id, prefijo, indice, extra, variante):
    """El índice es sobre `lower(btrim(...))`, igual que `strip().lower()` del
    login. Sin la normalización, «Sub@x.com» y «sub@x.com» serían dos filas y
    el mismo usuario para `/auth/login`."""
    n = _sufijo()
    base = f"norm-{n}@senavia-test.com"
    if variante == "MAYUSCULAS":
        choque = base.upper()
    elif variante == "MeZcLaDo":
        choque = base[:5].upper() + base[5:]
    else:
        choque = f"  {base}  "
    a, b = f"{prefijo}C{n}", f"{prefijo}D{n}"
    try:
        with get_session() as s:
            s.add(Model(**{campo_id: a, "Email_Address": base, **extra}))
            s.commit()
        with pytest.raises(IntegrityError) as fallo:
            with get_session() as s:
                s.add(Model(**{campo_id: b, "Email_Address": choque, **extra}))
                s.commit()
        _es_choque_de_correo(fallo, indice)
    finally:
        _limpiar(Model, campo_id, [a, b])


@pytest.mark.parametrize("Model,campo_id,prefijo,indice,extra", TABLAS)
def test_el_indice_es_PARCIAL_y_deja_pasar_los_vacios(Model, campo_id, prefijo, indice, extra):
    """El índice tiene predicado a propósito.

    `Email_Address` es NOT NULL en `technician` y `member`, y los datos
    heredados traen cadenas vacías. Un índice único total habría hecho
    imposible tener DOS filas sin correo — y la migración habría fallado al
    aplicarse en producción, o peor: habría bloqueado altas legítimas después.
    """
    n = _sufijo()
    a, b = f"{prefijo}E{n}", f"{prefijo}F{n}"
    try:
        with get_session() as s:
            s.add(Model(**{campo_id: a, "Email_Address": "", **extra}))
            s.add(Model(**{campo_id: b, "Email_Address": "   ", **extra}))
            s.commit()
        with get_session() as s:
            quedan = sorted(
                getattr(f, campo_id)
                for f in s.exec(select(Model).where(
                    getattr(Model, campo_id).in_([a, b]))).all())
        assert quedan == sorted([a, b]), "el índice bloqueó filas sin correo"
    finally:
        _limpiar(Model, campo_id, [a, b])


# ── El FORMATO, no sólo la unicidad ────────────────────────────────────────
#
# Todo lo de arriba asegura que el correo sea ÚNICO. La revisión adversarial
# midió que nadie comprobaba que fuera un CORREO:
#
#     PATCH /technician/TEC60187 {"Email_Address": "esto-no-es-un-correo"}
#     → 200, y el cuerpo lo devuelve tal cual.
#
# Y `Email_Address` es el nombre de usuario de acceso: con un teléfono ahí, la
# cuenta no puede entrar ni recuperar la contraseña. Ver
# `src/utils/validacion_correo.py`.

MALFORMADOS = ["esto-no-es-un-correo", "555-9999", "sin-arroba.com",
               "con espacio@x.com", "arroba@sin-punto", "@sin-local.com",
               "dos@@arrobas.com"]


@pytest.mark.parametrize("valor", MALFORMADOS)
def test_el_alta_rechaza_un_correo_con_forma_invalida(client, admin_headers, valor):
    tid = f"TECF{uuid.uuid4().int % 90000 + 10000}"
    resp = client.post("/technician/", headers=admin_headers, json={
        "ID_Technician": tid, "Name": "Formato", "Email_Address": valor,
        "Password": "Cl4ve-Buena!2026"})
    # La respuesta HTTP no es la verdad: se relee la BD. Y se BORRA lo que
    # hubiera, en un `finally`: si el validador se rompe, esta prueba escribe
    # una fila con un correo malformado, y como el índice único de
    # `e9c1correo` no deja repetirlo, la siguiente corrida daría 409 en vez de
    # 400 y el fallo parecería otro. Pasó midiendo la mutación de este mismo
    # arreglo: 7 filas basura dejaron 7 pruebas en rojo por el motivo
    # equivocado.
    try:
        assert resp.status_code == 400, (
            f"«{valor}» entró con {resp.status_code}: "
            f"{resp.get_data(as_text=True)[:200]}")
        with get_session() as s:
            fila = s.exec(select(Technician).where(
                Technician.Email_Address == valor)).first()
        assert fila is None, f"400 devuelto pero la fila con {valor!r} se escribió"
    finally:
        with get_session() as s:
            for fila in s.exec(select(Technician).where(
                    Technician.Email_Address == valor)).all():
                s.delete(fila)
            s.commit()


@pytest.mark.parametrize("valor", MALFORMADOS)
def test_el_update_rechaza_un_correo_con_forma_invalida(client, admin_headers, valor):
    """Es la puerta que la revisión midió abierta, y la alcanzable desde la UI:
    el formulario de edición del técnico expone `Email_Address`."""
    tid = f"TECG{uuid.uuid4().int % 90000 + 10000}"
    bueno = f"{tid.lower()}@senavia-test.com"
    alta = client.post("/technician/", headers=admin_headers, json={
        "ID_Technician": tid, "Name": "Formato Update",
        "Email_Address": bueno, "Password": "Cl4ve-Buena!2026"})
    assert alta.status_code == 201, alta.get_data(as_text=True)[:300]
    tid = (alta.get_json() or {}).get("ID_Technician") or tid
    try:
        resp = client.patch(f"/technician/{tid}", headers=admin_headers,
                            json={"Email_Address": valor})
        assert resp.status_code == 400, (
            f"«{valor}» entró con {resp.status_code}: "
            f"{resp.get_data(as_text=True)[:200]}")
        with get_session() as s:
            fila = s.exec(select(Technician).where(
                Technician.ID_Technician == tid)).first()
        assert fila.Email_Address == bueno, (
            f"400 devuelto pero el correo se cambió a {fila.Email_Address!r}")
    finally:
        with get_session() as s:
            fila = s.exec(select(Technician).where(
                Technician.ID_Technician == tid)).first()
            if fila:
                s.delete(fila)
                s.commit()


def test_un_correo_raro_pero_legitimo_si_entra():
    """El control. Sin esto, un validador que rechace TODO dejaría las dos
    pruebas de arriba en verde por el motivo equivocado.

    Es a propósito permisivo: rechazar de más rompería altas válidas, que es
    peor que el agujero que se está cerrando.
    """
    from src.models.TechnicianModel import TechnicianUpdate
    for bueno in ["a@b.co", "raro+etiqueta@sub.dominio.org",
                  "nombre.apellido@empresa.co.uk", "x1@y2.zz"]:
        v = TechnicianUpdate.model_validate({"Email_Address": bueno})
        assert v.Email_Address == bueno, bueno


def test_los_espacios_de_los_extremos_se_quitan_al_guardar():
    """Mismo motivo que O-05: `" sub@x.com "` guardado con espacios es una
    cuenta muda, porque el login busca normalizado y la fila no aparece."""
    from src.models.TechnicianModel import TechnicianUpdate
    v = TechnicianUpdate.model_validate({"Email_Address": "  sub@x.com \t"})
    assert v.Email_Address == "sub@x.com"
