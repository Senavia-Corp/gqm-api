# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.FinancialTransModel import FinancialTransaction, FTransactionCreate, FTransactionUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.auth.routes_protection import require_permission
from ..utils.audit import audit
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
# Blueprint de FinancialTransaction:
ftransaction_bp = Blueprint("ftransaction_blueprint",
                            __name__, url_prefix="/ftransaction")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los ftransaction
@ftransaction_bp.get("/")
@require_permission("ftransaction:read")
@handle_exceptions()
@paginate()
def list_ftransactions():
    with get_session() as session:

        statement = (
            select(FinancialTransaction)
            .options(
                joinedload(FinancialTransaction.financial_documents)
            )
        )
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        ft_data = [
            add_relationships(
                ft, ["financial_documents"])
            for ft in results
        ]

        return ft_data, 200


# Ruta para conseguir un ftransaction por ID
@ftransaction_bp.get("/<id_ftransaction>")
@require_permission("ftransaction:read")
@handle_exceptions()
def get_ftransaction(id_ftransaction):
    with get_session() as session:

        statement = (
            select(FinancialTransaction)
            .options(
                joinedload(FinancialTransaction.financial_documents)
            )
            .where(FinancialTransaction.ID_FTransaction == id_ftransaction)
        )

        obj = session.exec(statement).unique().first()

        if not obj:
            raise AppException("Financial Transaction not found", "not_found", 404)

        ft_data = add_relationships(
            obj, ["financial_documents"])

        return jsonify(ft_data), 200


# AGREGAR GETS POSIBLEMENTE POR CLIENT, JOB, ORDER Y SUBCONTRACTOR

# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un ftransaction
@ftransaction_bp.post("/")
@require_permission("ftransaction:create")
@handle_exceptions()
@audit("Financial Transaction created", entity_type="FinancialTransaction", id_from="response")
def create_ftransaction():
    data = request.get_json()
    create_ftransaction = FTransactionCreate.model_validate(data)
    obj = FinancialTransaction.model_validate(create_ftransaction)

    with get_session() as session:
        new_id = generate_custom_id(
            session, FinancialTransaction, "ID_FTransaction", "FT")
        obj.ID_FTransaction = new_id

        save_with_retry(session, obj)

        return jsonify(obj.model_dump()), 201


# Ruta para actualizar un ftransaction
@ftransaction_bp.patch("/<id_ftransaction>")
@require_permission("ftransaction:update")
@handle_exceptions()
@audit("Financial Transaction updated", entity_type="FinancialTransaction", id_param="id_ftransaction")
def update_ftransaction(id_ftransaction):
    data = request.get_json()
    with get_session() as session:
        obj = session.get(FinancialTransaction, id_ftransaction)
        if not obj:
            raise AppException("Financial Transaction not found", "not_found", 404)

        update_ftransaction = FTransactionUpdate.model_validate(data)
        update_data_dict = update_ftransaction.model_dump(
            exclude_unset=True)  # Crea dict limpio

        for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
            setattr(obj, key, value)

        save_with_retry(session, obj)

        return jsonify(obj.model_dump()), 200


# Ruta para eliminar un ftransaction
@ftransaction_bp.delete("/<id_ftransaction>")
@require_permission("ftransaction:delete")
@handle_exceptions()
@audit("Financial Transaction deleted", entity_type="FinancialTransaction", id_param="id_ftransaction")
def delete_ftransaction(id_ftransaction):
    with get_session() as session:
        obj = session.get(FinancialTransaction, id_ftransaction)
        if not obj:
            raise AppException("Financial Transaction not found", "not_found", 404)

        delete_with_retry(session, obj)

        return jsonify({"message": f"Deleted Financial Transaction {id_ftransaction}"}), 200
