from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.SubcontractorModel import Subcontractor, SubcontractorCreate, SubcontractorUpdate
from ..utils.id_generator import generate_custom_id
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from ..models.SubcontractorModel import podio_list_subcontractors

# Blueprint de Subcontractor
subcontractor_bp = Blueprint(
    "subcontractor_blueprint", __name__, url_prefix="/subcontractors")

# -------------------RUTAS CRUD-------------------#

# Ruta para conseguir la lista de todos los subcontratistas


@subcontractor_bp.get("/")
def list_subcontractors():
    try:
        with get_session() as session:
            results = session.exec(select(Subcontractor)).all()
            return jsonify([obj.model_dump() for obj in results]), 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(f"Error de base de datos al listar proveedores: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Error inesperado al listar proveedores: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un subcontratista por ID
@subcontractor_bp.get("/<id_subcontractor>")
def get_subcontractor(id_subcontractor):
    try:
        with get_session() as session:
            obj = session.get(Subcontractor, id_subcontractor)
            if not obj:
                return jsonify({"error": "Subcontractor not found"}), 404
            return jsonify(obj.model_dump()), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar proveedor {id_subcontractor}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar proveedores: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500

# Ruta para crear un subcontratista


@subcontractor_bp.post("/")
def create_subcontractor():
    try:
        data = request.get_json()
        create_subcontractor = SubcontractorCreate.model_validate(data)
        obj = Subcontractor.model_validate(create_subcontractor)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, Subcontractor, "ID_Subcontractor", "SUBC")
            obj.ID_Subcontractor = new_id

            session.add(obj)
            session.commit()
            session.refresh(obj)
            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:  # Cuando violas una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un proveedor con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Error de base de datos al crear proveedor: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Error inesperado durante la creación de proveedor: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500

# Ruta para actualizar un subcontratista


@subcontractor_bp.patch("/<id_subcontractor>")
def update_subcontractor(id_subcontractor):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(Subcontractor, id_subcontractor)
            if not obj:
                return jsonify({"error": "Subcontractor not found"}), 404

            update_subcontractor = SubcontractorUpdate.model_validate(data)
            update_data_dict = update_subcontractor.model_dump(
                exclude_unset=True)  # Crea dict limpio

            for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
                setattr(obj, key, value)

            session.add(obj)
            session.commit()
            session.refresh(obj)
            return jsonify(obj.model_dump()), 200

    # Exceptions de errores de validacion, integridad, infraestructura o inesperado del servidor.
    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de proveedor inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un proveedor con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al actualizar proveedor: {db_error}")
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
        print(f"Error inesperado al actualizar proveedor: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500

# Ruta para eliminar un subcontratista


@subcontractor_bp.delete("/<id_subcontractor>")
def delete_subcontractor(id_subcontractor):
    session = None
    try:
        with get_session() as session:
            obj = session.get(Subcontractor, id_subcontractor)
            if not obj:
                return jsonify({"error": "Subcontractor not found"}), 404
            session.delete(obj)
            session.commit()
            return jsonify({"message": f"Deleted Subcontractor {id_subcontractor}"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:  # En caso de borrar un proveedor que tiene productos asociados con Foreign Key
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el proveedor porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar proveedor: {db_error}")
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
        print(f"Error inesperado al eliminar proveedor: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# ---------- PODIO (Subcontractors App) ----------

@subcontractor_bp.get("/podio/items")
def subcontractors_from_podio():
    """
    GET /subcontractors/podio/items?limit=4&format=raw|normalized|extracted
    Parámetros opcionales:
      - offset, all=true|1|yes, view_id, category_mode (solo para normalized)
    """
    try:
        limit = int(request.args.get("limit", 200))
        offset = int(request.args.get("offset", 0))
        fetch_all = str(request.args.get("all", "false")
                        ).lower() in ("1", "true", "yes")
        view_id = request.args.get("view_id")
        fmt = (request.args.get("format") or "normalized").lower()
        category_mode = (request.args.get("category_mode") or "both").lower()

        data = podio_list_subcontractors(
            limit=limit, offset=offset, fetch_all=fetch_all, view_id=view_id,
            fmt=fmt, category_mode=category_mode
        )
        return jsonify(data), 200
    except request.HTTPError as e:
        return jsonify({"error": f"Podio API: {e.response.text}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 400
