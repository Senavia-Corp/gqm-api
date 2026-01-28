from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.SubcontractorModel import Subcontractor, SubcontractorCreate, SubcontractorUpdate
from ..models.TechnicianModel import Technician
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry


# Blueprint de Subcontractor
subcontractor_bp = Blueprint(
    "subcontractor_blueprint", __name__, url_prefix="/subcontractors")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los subcontratistas
@subcontractor_bp.get("/")
@paginate()
def list_subcontractors():
    try:
        with get_session() as session:

            statement = (
                select(Subcontractor)
                .options(
                    joinedload(Subcontractor.technicians)
                    .joinedload(Technician.tasks),
                    joinedload(Subcontractor.orders),
                    joinedload(Subcontractor.jobs),
                    joinedload(Subcontractor.attachments),
                    joinedload(Subcontractor.role),
                    joinedload(Subcontractor.tlactivity),
                    joinedload(Subcontractor.skills),
                    joinedload(Subcontractor.opportunities),
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            subcontr_data = [
                add_relationships(
                    subcontractor, ["technicians.tasks", "orders", "jobs", "attachments",
                                    "role", "tlactivity", "skills", "opportunities"])
                for subcontractor in results
            ]

            return subcontr_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(f"Error de base de datos al listar subcontratistas: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Error inesperado al listar subcontratistas: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un subcontratista por ID
@subcontractor_bp.get("/<id_subcontractor>")
def get_subcontractor(id_subcontractor):
    try:
        with get_session() as session:

            statement = (
                select(Subcontractor)
                .options(
                    joinedload(Subcontractor.technicians)
                    .joinedload(Technician.tasks),
                    joinedload(Subcontractor.orders),
                    joinedload(Subcontractor.jobs),
                    joinedload(Subcontractor.attachments),
                    joinedload(Subcontractor.role),
                    joinedload(Subcontractor.tlactivity),
                    joinedload(Subcontractor.skills),
                    joinedload(Subcontractor.opportunities),
                )
                .where(Subcontractor.ID_Subcontractor == id_subcontractor)
            )

            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "Subcontractor not found"}), 404

            subcontr_data = add_relationships(
                obj, ["technicians.tasks", "orders", "jobs", "attachments",
                      "role", "tlactivity", "skills", "opportunities"])

            return jsonify(subcontr_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar subcontratista {id_subcontractor}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar subcontratistas: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un subcontratista por estado
@subcontractor_bp.get("/status/<status>")
@paginate()
def list_subcontractor_by_state(status):
    try:
        with get_session() as session:

            statement = (
                select(Subcontractor)
                .options(
                    joinedload(Subcontractor.technicians)
                    .joinedload(Technician.tasks),
                    joinedload(Subcontractor.orders),
                    joinedload(Subcontractor.jobs),
                    joinedload(Subcontractor.attachments),
                )
                .where(Subcontractor.Status == status)
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            subcontr_data = [
                add_relationships(
                    subcontr, ["technicians.tasks", "orders", "jobs", "attachments"])
                for subcontr in results
            ]

            return subcontr_data, 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar subcontratista: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar subcontratista por estado: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un subcontratista por GQM compliance
@subcontractor_bp.get("/compliance/<compliance>")
@paginate()
def list_subcontractor_by_gqm_compliance(compliance):
    try:
        with get_session() as session:

            statement = (
                select(Subcontractor)
                .options(
                    joinedload(Subcontractor.technicians)
                    .joinedload(Technician.tasks),
                    joinedload(Subcontractor.orders),
                    joinedload(Subcontractor.jobs),
                    joinedload(Subcontractor.attachments),
                )
                .where(Subcontractor.Gqm_compliance == compliance)
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            subcontr_data = [
                add_relationships(
                    subcontr, ["technicians.tasks", "orders", "jobs", "attachments"])
                for subcontr in results
            ]

            return subcontr_data, 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar subcontratista: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(
            f"Error inesperado al listar subcontratista por Gqm compliance: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un subcontratista por GQM best service training
@subcontractor_bp.get("/bts/<bts>")
@paginate()
def list_subcontractor_by_gqm_bts(bts):
    try:
        with get_session() as session:

            statement = (
                select(Subcontractor)
                .options(
                    joinedload(Subcontractor.technicians)
                    .joinedload(Technician.tasks),
                    joinedload(Subcontractor.orders),
                    joinedload(Subcontractor.jobs),
                    joinedload(Subcontractor.attachments),
                )
                .where(Subcontractor.Gqm_best_service_training == bts)
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            subcontr_data = [
                add_relationships(
                    subcontr, ["technicians.tasks", "orders", "jobs", "attachments"])
                for subcontr in results
            ]

            return subcontr_data, 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar subcontratista: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(
            f"Error inesperado al listar subcontratista por Gqm compliance: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
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

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:  # Cuando violas una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un subcontratista con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Error de base de datos al crear subcontratista: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Error inesperado durante la creación de subcontratista: {e}")
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

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 200

    # Exceptions de errores de validacion, integridad, infraestructura o inesperado del servidor.
    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de subcontratista inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un subcontratista con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al actualizar subcontratista: {db_error}")
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
        print(f"Error inesperado al actualizar subcontratista: {e}")
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

            delete_with_retry(session, obj)

            return jsonify({"message": f"Deleted Subcontractor {id_subcontractor}"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:  # En caso de borrar un subcontratista que tiene productos asociados con Foreign Key
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el subcontratista porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar subcontratista: {db_error}")
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
        print(f"Error inesperado al eliminar subcontratista: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
