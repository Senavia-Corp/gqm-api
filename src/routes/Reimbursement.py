# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.ReimbursementModel import Reimbursement, ReimbursementCreate, ReimbursementUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger
from ..utils.commission_calculator import update_commission_reimbursement_total

# Blueprint de Reimbursement:
reimbursement_bp = Blueprint("reimbursement_blueprint", __name__,
                             url_prefix="/reimbursement")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los reimbursements
@reimbursement_bp.get("/")
@handle_exceptions()
@paginate()
def list_reimbursements():

    with get_session() as session:
        statement = (
            select(Reimbursement)
            .options(
                joinedload(Reimbursement.commission),
            )
        )
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        reimbursement_data = []

        for reimbursement in results:
            data = add_relationships(
                reimbursement, ["commission"])
            reimbursement_data.append(data)

        return reimbursement_data, 200


# Ruta para conseguir un reimbursement por ID
@reimbursement_bp.get("/<id_reimbursement>")
@handle_exceptions()
def get_reimbursement(id_reimbursement):

    with get_session() as session:
        statement = (
            select(Reimbursement)
            .options(
                joinedload(Reimbursement.commission),
            )
            .where(Reimbursement.ID_Reimbursement == id_reimbursement)
        )
        obj = session.exec(statement).unique().first()

        if not obj:
            raise AppException("Reimbursement not found.",
                               "reimbursement_not_found", 404)

        reimbursement_data = add_relationships(
            obj, ["commission"])

        return jsonify(reimbursement_data), 200


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un reimbursement
@reimbursement_bp.post("/")
@handle_exceptions()
def create_reimbursement():

    data = request.get_json()
    create_reimbursement = ReimbursementCreate.model_validate(data)
    obj = Reimbursement.model_validate(create_reimbursement)

    with get_session() as session:

        # ----------- 🔵 CREAR EN DB
        new_id = generate_custom_id(
            session, Reimbursement, "ID_Reimbursement", "RE")
        obj.ID_Reimbursement = new_id

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        # 🎯 TRIGGER: Actualizar el total en la comisión padre
        update_commission_reimbursement_total(obj.ID_Commission, session)
        session.commit()

        logger.info(
            "✅ Reimbursement creado y Comisión actualizada | id=%s",
            obj.ID_Reimbursement)
        return jsonify(obj.model_dump()), 201


# Ruta para actualizar un reimbursement
@reimbursement_bp.patch("/<id_reimbursement>")
@handle_exceptions()
def update_reimbursement(id_reimbursement):

    data = request.get_json()

    with get_session() as session:

        obj = session.get(Reimbursement, id_reimbursement)
        if not obj:
            raise AppException("Reimbursement not found.",
                               "reimbursement_not_found", 404)

        update_reimbursement = ReimbursementUpdate.model_validate(data)
        update_data_dict = update_reimbursement.model_dump(exclude_unset=True)

        # ----------- 🔄 ACTUALIZAR EN DB
        for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
            setattr(obj, key, value)

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        # 🎯 TRIGGER: Recalcular (por si cambió el Value o incluso la ID_Commission)
        update_commission_reimbursement_total(obj.ID_Commission, session)
        session.commit()

        logger.info(
            "🔄 Reimbursement y Comisión actualizados | id=%s",
            obj.ID_Reimbursement)
        return jsonify(obj.model_dump()), 200


# Ruta para eliminar un reimbursement
@reimbursement_bp.delete("/<id_reimbursement>")
@handle_exceptions()
def delete_reimbursement(id_reimbursement):

    with get_session() as session:
        obj = session.get(Reimbursement, id_reimbursement)
        if not obj:
            raise AppException("Reimbursement not found.",
                               "reimbursement_not_found", 404)

        # Guardamos la ID de la comisión antes de borrar el registro
        comm_id = obj.ID_Commission

        # ----------- 🔴 BORRAR EN DB
        delete_with_retry(session, obj)

        # 🎯 TRIGGER: Restar el valor del total de la comisión
        update_commission_reimbursement_total(comm_id, session)
        session.commit()

        logger.info(
            "🗑️ Reimbursement eliminado y Comisión actualizada | id=%s",
            id_reimbursement)
        return jsonify({"message": f"Reimbursement {id_reimbursement} eliminado"}), 200
