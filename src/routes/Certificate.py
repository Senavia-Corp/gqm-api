# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.CertificateModel import Certificate, CertificateCreate, CertificateUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.auth.routes_protection import (
    require_permission, portal_scope, portal_owns_subcontractor)
from ..utils.audit import audit
from ..utils.middleware.logs.logs import logger

# Blueprint de Certificate:
certificate_bp = Blueprint("certificate_blueprint", __name__,
                           url_prefix="/certificate")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los certificates
@certificate_bp.get("/")
@require_permission("certificate:read")
@handle_exceptions()
@paginate()
def list_certificates():

    with get_session() as session:
        statement = (
            select(Certificate)
            .options(
                joinedload(Certificate.attachments)
            )
        )

        # P-06 (S2): el listado entregaba los certificados de cumplimiento de
        # TODOS los subcontratistas. Para un rol de portal se acota al propio
        # id. Es una «lista por relacion»: el sub sigue viendo LOS SUYOS y, si
        # no tiene ninguno, la respuesta correcta es 200 con [] (no un 404).
        # El staff (full_admin, gqm_member) no se ve afectado: portal_scope()
        # devuelve (None, None) y el statement queda tal cual.
        rol, uid = portal_scope()
        if rol == "subcontractor":
            statement = statement.where(Certificate.ID_Subcontractor == uid)
        elif rol is not None:
            # Tecnico: su politica no trae `certificate:read`, asi que el
            # decorador ya corta antes; esto es la segunda linea de defensa.
            return [], 200

        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        certificates_data = []

        for certificates in results:
            data = add_relationships(
                certificates, ["attachments"])
            certificates_data.append(data)

        return certificates_data, 200


# Ruta para conseguir un certificate por ID
@certificate_bp.get("/<id_certificate>")
@require_permission("certificate:read")
@handle_exceptions()
def get_certificate(id_certificate):

    with get_session() as session:
        statement = (
            select(Certificate)
            .options(
                joinedload(Certificate.attachments)
            )
            .where(Certificate.ID_Certificate == id_certificate)
        )
        obj = session.exec(statement).unique().first()

        # P-06 (S2): la lectura por id no comprobaba pertenencia, asi que un
        # sub leia el certificado de cumplimiento de otro con solo saber el id.
        # Modismo de Tasks.py:170 («if not obj or not pertenece: 404»): para un
        # rol de portal el recurso ajeno responde 404 y no 403, porque un 403
        # confirma que existe y deja la ruta enumerable (Job.py:506-507).
        # Un certificado sin ID_Subcontractor tampoco es de nadie del portal.
        if not obj or not portal_owns_subcontractor(obj.ID_Subcontractor):
            raise AppException("Certificate not found.",
                               "certificate_not_found", 404)

        certificates_data = add_relationships(
            obj, ["attachments"])

        return jsonify(certificates_data), 200


# Ruta para conseguir certificates por subcontratista
@certificate_bp.get("/subcontractor/<subc>")
@require_permission("certificate:read")
@handle_exceptions()
@paginate()
def list_cert_by_subcontractor(subc):

    # P-06 (S2): el <subc> del path se usaba CRUDO en la consulta de abajo, sin
    # compararlo nunca con el id del llamante: el sub A leia los certificados
    # de cumplimiento del sub B. Se comprueba pertenencia ANTES de consultar y
    # un id ajeno responde 404, no 403 (Job.py:506-507: el 403 confirma la
    # existencia y hace la ruta enumerable). Sigue siendo una «lista por
    # relacion»: para el propio sub sin certificados la respuesta es 200 con []
    # (abajo, sin tocar). El staff pasa: portal_owns_subcontractor() devuelve
    # True cuando el llamante no es de portal.
    if not portal_owns_subcontractor(subc):
        raise AppException("Certificate not found.",
                           "certificate_not_found", 404)

    with get_session() as session:
        statement = (
            select(Certificate)
            .options(
                joinedload(Certificate.attachments)
            )
            .where(Certificate.ID_Subcontractor == subc)
        )
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        certificates_data = [
            add_relationships(
                certificate, ["attachments"])
            for certificate in results
        ]

        return certificates_data, 200


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un certificate
@certificate_bp.post("/")
@require_permission("certificate:create")
@handle_exceptions()
@audit("Certificate created", entity_type="Certificate", id_from="response")
def create_certificate():

    data = request.get_json()
    create_certificate = CertificateCreate.model_validate(data)
    obj = Certificate.model_validate(create_certificate)

    with get_session() as session:

        # ----------- 🔵 CREAR EN DB
        new_id = generate_custom_id(
            session, Certificate, "ID_Certificate", "CER")
        obj.ID_Certificate = new_id

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        logger.info(
            "✅ Certificate creado | certificate_id=%s",
            obj.ID_Certificate
        )

        return jsonify(obj.model_dump()), 201


# Ruta para actualizar un certificate
@certificate_bp.patch("/<id_certificate>")
@require_permission("certificate:update")
@handle_exceptions()
@audit("Certificate updated", entity_type="Certificate", id_param="id_certificate")
def update_certificate(id_certificate):

    data = request.get_json()

    with get_session() as session:

        obj = session.get(Certificate, id_certificate)
        if not obj:
            raise AppException("Certificate not found.",
                               "certificate_not_found", 404)

        update_certificate = CertificateUpdate.model_validate(data)
        update_data_dict = update_certificate.model_dump(exclude_unset=True)

        # ----------- 🔄 ACTUALIZAR EN DB
        for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
            setattr(obj, key, value)

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        logger.info(
            "🔄 Certificate actualizado | certificate_id=%s",
            obj.ID_Certificate
        )

        return jsonify(obj.model_dump()), 200


# Ruta para eliminar un certificate
@certificate_bp.delete("/<id_certificate>")
@require_permission("certificate:delete")
@handle_exceptions()
@audit("Certificate deleted", entity_type="Certificate", id_param="id_certificate")
def delete_certificate(id_certificate):

    with get_session() as session:
        obj = session.get(Certificate, id_certificate)
        if not obj:
            raise AppException("Certificate not found.",
                               "certificate_not_found", 404)

        # ----------- 🔴 BORRAR EN DB
        delete_with_retry(session, obj)

        logger.info(
            "🗑️ Certificate eliminado | certificate_id=%s",
            id_certificate
        )

        return jsonify({
            "message": f"Certificate {id_certificate} eliminado correctamente"
        }), 200
