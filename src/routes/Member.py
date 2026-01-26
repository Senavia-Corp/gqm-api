# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.MemberModel import Member, MemberCreate, MemberUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.auth.password_hashing import hash_password

# Blueprint de Member:
member_bp = Blueprint("member_blueprint", __name__, url_prefix="/member")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los miembros GQM
@member_bp.get("/")
@paginate()  # decorador de paginación
def list_members():
    try:
        with get_session() as session:
            # Trae los miembros GQM con sus trabajos en una sola consulta
            statement = (
                select(Member)
                .options(
                    joinedload(Member.jobs),
                    joinedload(Member.permissions),
                    joinedload(Member.role),
                    joinedload(Member.tlactivity),
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404   # El decorador se encarga del formato final

            member_data = []

            for member in results:
                data = add_relationships(
                    member, ["jobs", "permissions", "role", "tlactivity"])
                member_data.append(data)

            return member_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(f"Error de base de datos al listar miembros GQM: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Error inesperado al listar miembros GQM: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un miembro GQM por ID_Member
@member_bp.get("/<id_member>")
def get_member_by_id(id_member):
    try:
        with get_session() as session:
            statement = (
                select(Member)
                .options(
                    joinedload(Member.jobs),
                    joinedload(Member.permissions),
                    joinedload(Member.role),
                    joinedload(Member.tlactivity),
                )
                .where(Member.ID_Member == id_member)
            )

            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "Member not found"}), 404

            # Construir JSON limpio con la info de los jobs
            member_data = add_relationships(
                obj, ["jobs", "permissions", "role", "tlactivity"])

            return jsonify(member_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar miembro GQM {id_member}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar miembros GQM: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un miembro GQM
@member_bp.post("/")
def create_member():
    try:
        data = request.get_json()
        create_member = MemberCreate.model_validate(data)
        obj = Member.model_validate(create_member)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:

            obj.Password = hash_password(obj.Password)  # Hash al password

            new_id = generate_custom_id(
                session, Member, "ID_Member", "MEM")
            obj.ID_Member = new_id

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
            detail = "Ya existe un miembro GQM con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Error de base de datos al crear miembro GQM: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Error inesperado durante la creación de miembro GQM: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar un miembro GQM
@member_bp.patch("/<id_member>")
def update_member(id_member):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(Member, id_member)
            if not obj:
                return jsonify({"error": "GQM Member not found"}), 404

            update_member = MemberUpdate.model_validate(data)
            update_data_dict = update_member.model_dump(
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
            "detail": "Error de validación: Datos de miembro GQM inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un miembro GQM con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al actualizar miembro GQM: {db_error}")
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
        print(f"Error inesperado al actualizar miembro GQM: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para eliminar un miembro GQM
@member_bp.delete("/<id_member>")
def delete_member(id_member):
    session = None
    try:
        with get_session() as session:
            obj = session.get(Member, id_member)
            if not obj:
                return jsonify({"error": "GQM Member not found"}), 404
            session.delete(obj)
            session.commit()
            return jsonify({"message": f"Deleted GQM Member {id_member}"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:  # En caso de borrar un miembro GQM que tiene productos asociados con Foreign Key
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el miembro GQM porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar miembro GQM: {db_error}")
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
        print(f"Error inesperado al eliminar miembro GQM: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
