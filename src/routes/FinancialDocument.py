# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.FinancialDocModel import FinancialDocument, FDocCreate, FDocUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry


# Blueprint de FinancialDocument:
fdocument_bp = Blueprint("fdocument_blueprint",
                         __name__, url_prefix="/fdocument")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los fdocument
@fdocument_bp.get("/")
@paginate()
def list_fdocument():
    try:
        with get_session() as session:

            statement = (
                select(FinancialDocument)
                .options(
                    joinedload(FinancialDocument.financial_doc_items),
                    joinedload(FinancialDocument.financial_transactions),
                    joinedload(FinancialDocument.client),
                    joinedload(FinancialDocument.job),
                    joinedload(FinancialDocument.order),
                    joinedload(FinancialDocument.subcontractor),
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            fd_data = [
                add_relationships(
                    fd, ["financial_doc_items", "financial_transactions",
                         "client", "job", "order", "subcontractor"])
                for fd in results
            ]

            return fd_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(f"Error de base de datos al listar fdocuments: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Error inesperado al listar fdocuments: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un fdocument por ID
@fdocument_bp.get("/<id_fdocument>")
def get_fdocument(id_fdocument):
    try:
        with get_session() as session:

            statement = (
                select(FinancialDocument)
                .options(
                    joinedload(FinancialDocument.financial_doc_items),
                    joinedload(FinancialDocument.financial_transactions),
                    joinedload(FinancialDocument.client),
                    joinedload(FinancialDocument.job),
                    joinedload(FinancialDocument.order),
                    joinedload(FinancialDocument.subcontractor),
                )
                .where(FinancialDocument.ID_FinancialDoc == id_fdocument)
            )

            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "FinancialDocument not found"}), 404

            fd_data = add_relationships(
                obj, ["financial_doc_items", "financial_transactions",
                      "client", "job", "order", "subcontractor"])

            return jsonify(fd_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar fdocument {id_fdocument}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar fdocument: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un fdocument
@fdocument_bp.post("/")
def create_fdocument():
    try:
        data = request.get_json()
        create_fdocument = FDocCreate.model_validate(data)
        obj = FinancialDocument.model_validate(create_fdocument)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, FinancialDocument, "ID_FinancialDoc", "FD")
            obj.ID_FinancialDoc = new_id

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:  # Cuando viola una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un fdocument con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Error de base de datos al crear fdocument: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Error inesperado durante la creación de fdocument: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar un fdocument
@fdocument_bp.patch("/<id_fdocument>")
def update_fdocument(id_fdocument):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(FinancialDocument, id_fdocument)
            if not obj:
                return jsonify({"error": "FinancialDocument not found"}), 404

            update_fdocument = FDocUpdate.model_validate(data)
            update_data_dict = update_fdocument.model_dump(
                exclude_unset=True)  # Crea dict limpio

            for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
                setattr(obj, key, value)

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 200

    # Exceptions de errores de validacion, integridad, infraestructura o inesperado del servidor.
    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de fdocument inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un fdocument con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al actualizar fdocument: {db_error}")
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
        print(f"Error inesperado al actualizar fdocument: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para eliminar un fdocument
@fdocument_bp.delete("/<id_fdocument>")
def delete_fdocument(id_fdocument):
    session = None
    try:
        with get_session() as session:
            obj = session.get(FinancialDocument, id_fdocument)
            if not obj:
                return jsonify({"error": "FinancialDocument not found"}), 404

            delete_with_retry(session, obj)

            return jsonify({"message": f"Deleted FinancialDocument {id_fdocument}"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:  # En caso de borrar un fdocument que tiene productos asociados con Foreign Key
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el fdocument porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar fdocument: {db_error}")
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
        print(f"Error inesperado al eliminar fdocument: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
