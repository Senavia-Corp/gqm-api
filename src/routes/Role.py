# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.RoleModel import Role, RoleCreate, RoleUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from src.utils.middleware.auth.routes_protection import require_permission


# Blueprint de Role:
role_bp = Blueprint("role_blueprint", __name__, url_prefix="/role")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los roles
@role_bp.get("/")
@require_permission("role:read")
@paginate()
def list_roles():
    try:
        with get_session() as session:

            statement = (
                select(Role)
                .options(
                    joinedload(Role.members),
                    joinedload(Role.subcontractors),
                    joinedload(Role.permissions),
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            role_data = [
                add_relationships(
                    role, ["members", "subcontractors", "permissions"])
                for role in results
            ]

            return role_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(f"Error de base de datos al listar roles: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Error inesperado al listar roles: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un role por ID
@role_bp.get("/<id_role>")
@require_permission("role:read")
def get_role(id_role):
    try:
        with get_session() as session:

            statement = (
                select(Role)
                .options(
                    joinedload(Role.members),
                    joinedload(Role.subcontractors),
                    joinedload(Role.permissions),
                )
                .where(Role.ID_Role == id_role)
            )

            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "Role not found"}), 404

            role_data = add_relationships(
                obj, ["members", "subcontractors", "permissions"])

            return jsonify(role_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar role {id_role}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar role: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un role
@role_bp.post("/")
@require_permission("role:create")
def create_role():
    try:
        data = request.get_json()
        create_role = RoleCreate.model_validate(data)
        obj = Role.model_validate(create_role)

        # RoleBase tiene TODOS los campos opcionales, asi que un POST con {} se
        # validaba y creaba un rol con Name/Active/Description a NULL. Esos
        # roles fantasma se acumulan (develop llego a tener 4), salen en el
        # panel como «Inactive / — / 0 permissions» y cleanup_rbac.py tiene un
        # paso 4 solo para barrerlos. Un rol sin nombre no es utilizable.
        if not (obj.Name or "").strip():
            return jsonify({"detail": "Name es obligatorio para crear un role."}), 400

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, Role, "ID_Role", "ROL")
            obj.ID_Role = new_id

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:  # Cuando viola una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un role con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Error de base de datos al crear role: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Error inesperado durante la creación de role: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar un role
@role_bp.patch("/<id_role>")
@require_permission("role:update")
def update_role(id_role):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(Role, id_role)
            if not obj:
                return jsonify({"error": "Role not found"}), 404

            update_role = RoleUpdate.model_validate(data)
            update_data_dict = update_role.model_dump(
                exclude_unset=True)  # Crea dict limpio

            for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
                setattr(obj, key, value)

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 200

    # Exceptions de errores de validacion, integridad, infraestructura o inesperado del servidor.
    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de role inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un role con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al actualizar role: {db_error}")
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
        print(f"Error inesperado al actualizar role: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para eliminar un role
@role_bp.delete("/<id_role>")
@require_permission("role:delete")
def delete_role(id_role):
    session = None
    try:
        with get_session() as session:
            obj = session.get(Role, id_role)
            if not obj:
                return jsonify({"error": "Role not found"}), 404

            delete_with_retry(session, obj)

            return jsonify({"message": f"Deleted Role {id_role}"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:  # En caso de borrar un role que tiene productos asociados con Foreign Key
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el role porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar role: {db_error}")
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
        print(f"Error inesperado al eliminar role: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
