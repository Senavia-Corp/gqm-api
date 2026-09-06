"""Pertenencia de portal: los helpers sobre los que se apoya el bloque A.

`portal_owns_technician` y `portal_owns_subcontractor` son la primitiva que
cierra P-01, P-02, P-05 y P-06. Se prueban aqui directamente, aparte de por
HTTP, porque un fallo en ellas se propaga a cinco rutas a la vez y conviene que
el test que se ponga rojo senale la causa y no el sintoma.

Depende de los sujetos que siembra `scripts/seed_portal_audit.py`.
"""
import pytest
from flask import g

from src.database.db_sqlmodel import get_session
from src.utils.middleware.auth.routes_protection import (
    portal_owns_subcontractor, portal_owns_technician)

STAFF = {"id": "MEM60001", "role": "member"}
SUB_A = {"id": "SUBC60001", "role": "subcontractor"}
TEC_A = {"id": "TEC60001", "role": "technician"}


@pytest.mark.parametrize("usuario,objetivo,esperado,motivo", [
    (STAFF, "TEC60002", True,  "el staff alcanza a cualquier tecnico"),
    (SUB_A, "TEC60001", True,  "el sub alcanza a SU tecnico"),
    (SUB_A, "TEC60002", False, "P-01: el sub NO alcanza al tecnico de otro sub"),
    (SUB_A, "TEC60003", False, "el sub NO alcanza a un tecnico independiente"),
    (SUB_A, "TEC-NO-EXISTE", False, "un id inexistente no pertenece a nadie"),
    (TEC_A, "TEC60001", True,  "el tecnico se alcanza a si mismo"),
    (TEC_A, "TEC60002", False, "P-01: el tecnico NO alcanza a otro tecnico"),
])
def test_pertenencia_de_tecnico(app, usuario, objetivo, esperado, motivo):
    with app.test_request_context():
        g.current_user = usuario
        with get_session() as session:
            assert portal_owns_technician(session, objetivo) is esperado, motivo


@pytest.mark.parametrize("usuario,objetivo,esperado,motivo", [
    (STAFF, "SUBC60002", True,  "el staff alcanza a cualquier subcontratista"),
    (SUB_A, "SUBC60001", True,  "el sub se alcanza a si mismo"),
    (SUB_A, "SUBC60002", False, "P-05: el sub NO alcanza a otro sub"),
    (TEC_A, "SUBC60001", False, "el tecnico no alcanza fichas de subcontratista"),
])
def test_pertenencia_de_subcontratista(app, usuario, objetivo, esperado, motivo):
    with app.test_request_context():
        g.current_user = usuario
        assert portal_owns_subcontractor(objetivo) is esperado, motivo


def test_sin_usuario_no_se_bloquea_al_staff(app):
    """Scripts y tareas de fondo corren sin `g.current_user`: no deben quedar
    bloqueados por una guarda pensada para peticiones de portal."""
    with app.test_request_context():
        with get_session() as session:
            assert portal_owns_technician(session, "TEC60002") is True
        assert portal_owns_subcontractor("SUBC60002") is True
