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


# Blueprint de FinancialTransaction:
ftransaction_bp = Blueprint("ftransaction_blueprint",
                            __name__, url_prefix="/ftransaction")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los ftransaction
@ftransaction_bp.get("/")
@paginate()
def list_ftransactions():
    try:
        with get_session() as session:

            statement = (
                select(FinancialTransaction)
                .options(
                    joinedload(FinancialTransaction.financial_documents)
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            ft_data = [
                add_relationships(
                    ft, ["financial_documents"])
                for ft in results
            ]

            return ft_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(f"Error de base de datos al listar ftransactions: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Error inesperado al listar ftransactions: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un ftransaction por ID
@ftransaction_bp.get("/<id_ftransaction>")
def get_ftransaction(id_ftransaction):
    try:
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
                return jsonify({"error": "Financial Transaction not found"}), 404

            ft_data = add_relationships(
                obj, ["financial_documents"])

            return jsonify(ft_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar ftransaction {id_ftransaction}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar ftransaction: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# AGREGAR GETS POSIBLEMENTE POR CLIENT, JOB, ORDER Y SUBCONTRACTOR

# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un ftransaction
@ftransaction_bp.post("/")
def create_ftransaction():
    try:
        data = request.get_json()
        create_ftransaction = FTransactionCreate.model_validate(data)
        obj = FinancialTransaction.model_validate(create_ftransaction)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, FinancialTransaction, "ID_FTransaction", "FT")
            obj.ID_FTransaction = new_id

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:  # Cuando viola una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un ftransaction con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Error de base de datos al crear ftransaction: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Error inesperado durante la creación de ftransaction: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar un ftransaction
@ftransaction_bp.patch("/<id_ftransaction>")
def update_ftransaction(id_ftransaction):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(FinancialTransaction, id_ftransaction)
            if not obj:
                return jsonify({"error": "Financial Transaction not found"}), 404

            update_ftransaction = FTransactionUpdate.model_validate(data)
            update_data_dict = update_ftransaction.model_dump(
                exclude_unset=True)  # Crea dict limpio

            for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
                setattr(obj, key, value)

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 200

    # Exceptions de errores de validacion, integridad, infraestructura o inesperado del servidor.
    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de ftransaction inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un ftransaction con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al actualizar ftransaction: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        if session:
            try:
                session.rollback()
            except Exception:
                pass
        print(f"Error inesperado al actualizar ftransaction: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para eliminar un ftransaction
@ftransaction_bp.delete("/<id_ftransaction>")
def delete_ftransaction(id_ftransaction):
    session = None
    try:
        with get_session() as session:
            obj = session.get(FinancialTransaction, id_ftransaction)
            if not obj:
                return jsonify({"error": "Financial Transaction not found"}), 404

            delete_with_retry(session, obj)

            return jsonify({"message": f"Deleted Financial Transaction {id_ftransaction}"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:  # En caso de borrar un ftransaction que tiene productos asociados con Foreign Key
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el ftransaction porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar ftransaction: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        if session:
            try:
                session.rollback()
            except Exception:
                pass
        print(f"Error inesperado al eliminar ftransaction: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
