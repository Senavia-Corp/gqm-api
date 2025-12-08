# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.TechnicianModel import Technician, TechnicianCreate, TechnicianUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.auth.password_hashing import hash_password

# Blueprint de Technician:
technician_bp = Blueprint("technician_blueprint",
                          __name__, url_prefix="/technician")

# -------------------RUTAS CRUD-------------------#

# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los técnicos


@technician_bp.get("/")
@paginate()  # decorador de paginación
def list_technicians():
    try:
        with get_session() as session:
            statement = (
                select(Technician)
                .options(
                    joinedload(Technician.subcontractor),
                    joinedload(Technician.tasks)
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404   # El decorador se encarga del formato final

            technician_data = []

            for tech in results:
                data = add_relationships(tech, ["subcontractor", "tasks"])
                technician_data.append(data)

            return technician_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(f"Error de base de datos al listar técnicos: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Error inesperado al listar técnicos: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un técnico por ID_Technician
@technician_bp.get("/<id_technician>")
def get_tech_by_id(id_technician):
    try:
        with get_session() as session:
            statement = (
                select(Technician)
                .options(
                    joinedload(Technician.subcontractor),
                    joinedload(Technician.tasks)
                )
                .where(Technician.ID_Technician == id_technician)
            )

            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "Technician not found"}), 404

            # Construir JSON limpio con la info del cliente
            technician_data = add_relationships(
                obj, ["subcontractor", "tasks"])

            return jsonify(technician_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar técnico {id_technician}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar técnico: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un técnico
@technician_bp.post("/")
def create_techician():
    try:
        data = request.get_json()
        create_techician = TechnicianCreate.model_validate(data)
        obj = Technician.model_validate(create_techician)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:

            obj.Password = hash_password(obj.Password)  # Hash al password

            new_id = generate_custom_id(
                session, Technician, "ID_Technician", "TEC")
            obj.ID_Technician = new_id

            session.add(obj)
            session.commit()
            session.refresh(obj)

            response = obj.model_dump()
            response.pop("Password", None)

            return jsonify(response), 201

    except IntegrityError as e:  # Cuando violas una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un técnico con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Error de base de datos al crear técnico: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Error inesperado durante la creación de técnico: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar un técnico
@technician_bp.patch("/<id_technician>")
def update_technician(id_technician):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(Technician, id_technician)
            if not obj:
                return jsonify({"error": "Technician not found"}), 404

            update_technician = TechnicianUpdate.model_validate(data)
            update_data_dict = update_technician.model_dump(
                exclude_unset=True)  # Crea dict limpio

            # Hash al passsword si se actualiza
            if "Password" in update_data_dict:
                update_data_dict["Password"] = hash_password(
                    update_data_dict["Password"]
                )

            for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
                setattr(obj, key, value)

            session.add(obj)
            session.commit()
            session.refresh(obj)

            response = obj.model_dump()
            response.pop("Password", None)

            return jsonify(response), 200

    # Exceptions de errores de validacion, integridad, infraestructura o inesperado del servidor.
    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de técnico inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un técnico con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al actualizar técnico: {db_error}")
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
        print(f"Error inesperado al actualizar técnico: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para eliminar un técnico
@technician_bp.delete("/<id_technician>")
def delete_technician(id_technician):
    session = None
    try:
        with get_session() as session:
            obj = session.get(Technician, id_technician)
            if not obj:
                return jsonify({"error": "Technician not found"}), 404
            session.delete(obj)
            session.commit()
            return jsonify({"message": f"Deleted Technician {id_technician}"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:  # En caso de borrar un técnico que tiene productos asociados con Foreign Key
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el técnico porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar técnico: {db_error}")
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
        print(f"Error inesperado al eliminar técnico: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
