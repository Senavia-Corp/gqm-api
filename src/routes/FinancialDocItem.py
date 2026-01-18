# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.FinancialDocItemModel import FinancialDoc_Item, FDItemCreate, FDItemUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry


# Blueprint de FinancialDoc_Item:
fdoc_item_bp = Blueprint("fdoc_item_blueprint",
                         __name__, url_prefix="/fdoc_item")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los FinancialDoc_Item
@fdoc_item_bp.get("/")
@paginate()
def list_fditems():
    try:
        with get_session() as session:

            statement = (
                select(FinancialDoc_Item)
                .options(
                    joinedload(FinancialDoc_Item.financial_document)
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            fditem_data = [
                add_relationships(
                    fditem, ["financial_document"])
                for fditem in results
            ]

            return fditem_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(
            f"Error de base de datos al listar los items del financial document: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(
            f"Error inesperado al listar los items del financial document: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un FinancialDoc_Item por ID
@fdoc_item_bp.get("/<id_fdocitem>")
def get_fditem(id_fdocitem):
    try:
        with get_session() as session:

            statement = (
                select(FinancialDoc_Item)
                .options(
                    joinedload(FinancialDoc_Item.financial_document)
                )
                .where(FinancialDoc_Item.ID_FDItem == id_fdocitem)
            )

            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "FinancialDoc Item not found"}), 404

            fditem_data = add_relationships(
                obj, ["financial_document"])

            return jsonify(fditem_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar item del financial document {id_fdocitem}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(
            f"Error inesperado al listar los items del financial document: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un FinancialDoc_Item
@fdoc_item_bp.post("/")
def create_fditem():
    try:
        data = request.get_json()
        create_fditem = FDItemCreate.model_validate(data)
        obj = FinancialDoc_Item.model_validate(create_fditem)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, FinancialDoc_Item, "ID_FDItem", "FDI")
            obj.ID_FDItem = new_id

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:  # Cuando viola una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un item del financial document con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(
            f"Error de base de datos al crear item del financial document: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(
            f"Error inesperado durante la creación del item del financial document: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar un FinancialDoc_Item
@fdoc_item_bp.patch("/<id_fdocitem>")
def update_fditem(id_fdocitem):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(FinancialDoc_Item, id_fdocitem)
            if not obj:
                return jsonify({"error": "FinancialDoc Item not found"}), 404

            update_fditem = FDItemUpdate.model_validate(data)
            update_data_dict = update_fditem.model_dump(
                exclude_unset=True)  # Crea dict limpio

            for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
                setattr(obj, key, value)

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 200

    # Exceptions de errores de validacion, integridad, infraestructura o inesperado del servidor.
    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de item del financial document inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un item del financial document con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al actualizar item del financial document: {db_error}")
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
        print(
            f"Error inesperado al actualizar item del financial document: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para eliminar un FinancialDoc_Item
@fdoc_item_bp.delete("/<id_fdocitem>")
def delete_fditem(id_fdocitem):
    session = None
    try:
        with get_session() as session:
            obj = session.get(FinancialDoc_Item, id_fdocitem)
            if not obj:
                return jsonify({"error": "FinancialDoc Item not found"}), 404

            delete_with_retry(session, obj)

            return jsonify({"message": f"Deleted FinancialDoc Item {id_fdocitem}"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:  # En caso de borrar un item del financial document que tiene productos asociados con Foreign Key
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el item del financial document porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al eliminar item del financial document: {db_error}")
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
        print(f"Error inesperado al eliminar item del financial document: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
