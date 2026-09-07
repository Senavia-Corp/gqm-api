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
