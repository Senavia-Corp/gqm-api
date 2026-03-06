# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.TLActivityModel import TLActivity, TLActivityCreate, TLActivityUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry


# Blueprint de TLActivity:
tlactivity_bp = Blueprint("tlactivity_blueprint",
                          __name__, url_prefix="/tlactivity")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los tlactivity
@tlactivity_bp.get("/")
@paginate()
def list_tlactivities():
    try:
        with get_session() as session:

            statement = (
                select(TLActivity)
                .options(
                    joinedload(TLActivity.job),
                    joinedload(TLActivity.member),
                    joinedload(TLActivity.technician),
                    joinedload(TLActivity.subcontractor),
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            tla_data = [
                add_relationships(
                    tla, ["job", "member", "technician", "subcontractor"])
                for tla in results
            ]

            return tla_data, 200

    except SQLAlchemyError as db_error:
        print(f"Error de base de datos al listar tlactivities: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar tlactivities: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un tlactivity por ID
@tlactivity_bp.get("/<id_tlactivity>")
def get_tlactivity(id_tlactivity):
    try:
        with get_session() as session:

            statement = (
                select(TLActivity)
                .options(
                    joinedload(TLActivity.job),
                    joinedload(TLActivity.member),
                    joinedload(TLActivity.technician),
                    joinedload(TLActivity.subcontractor),
                )
                .where(TLActivity.ID_TLActivity == id_tlactivity)
            )

            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "TLActivity not found"}), 404

            tla_data = add_relationships(
                obj, ["job", "member", "technician", "subcontractor"])

            return jsonify(tla_data), 200

    except SQLAlchemyError as db_error:
        print(f"Error de base de datos al buscar tlactivity {id_tlactivity}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar tlactivity: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# ── NEW ──────────────────────────────────────────────────────────────────────
# Ruta para conseguir todos los registros de timeline de un Job específico
# GET /tlactivity/job/<id_job>
# Ordenado por Action_datetime DESC (más reciente primero)
@tlactivity_bp.get("/job/<id_job>")
@paginate()
def get_tlactivities_by_job(id_job):
    try:
        with get_session() as session:

            statement = (
                select(TLActivity)
                .options(
                    joinedload(TLActivity.member),
                    joinedload(TLActivity.technician),
                    joinedload(TLActivity.subcontractor),
                )
                .where(TLActivity.ID_Jobs == id_job)
                .order_by(TLActivity.Action_datetime.desc())
            )

            results = session.exec(statement).unique().all()

            if not results:
                return [], 200   # @paginate() maneja el formato final

            tla_data = [
                add_relationships(tla, ["member", "technician", "subcontractor"])
                for tla in results
            ]

            return tla_data, 200

    except SQLAlchemyError as db_error:
        print(f"Error de base de datos al listar tlactivities del job {id_job}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar tlactivities del job {id_job}: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500
# ─────────────────────────────────────────────────────────────────────────────


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un tlactivity
@tlactivity_bp.post("/")
def create_tlactivity():
    try:
        data = request.get_json()
        create_tlactivity = TLActivityCreate.model_validate(data)
        obj = TLActivity.model_validate(create_tlactivity)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, TLActivity, "ID_TLActivity", "TLA")
            obj.ID_TLActivity = new_id

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:
        session.rollback()
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un tlactivity con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        session.rollback()
        print(f"Error de base de datos al crear tlactivity: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass
        print(f"Error inesperado durante la creación de tlactivity: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar un tlactivity
@tlactivity_bp.patch("/<id_tlactivity>")
def update_tlactivity(id_tlactivity):
    session = None
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(TLActivity, id_tlactivity)
            if not obj:
                return jsonify({"error": "TLActivity not found"}), 404

            update_tlactivity = TLActivityUpdate.model_validate(data)
            update_data_dict = update_tlactivity.model_dump(exclude_unset=True)

            for key, value in update_data_dict.items():
                setattr(obj, key, value)

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 200

    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de tlactivity inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un tlactivity con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al actualizar tlactivity: {db_error}")
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
        print(f"Error inesperado al actualizar tlactivity: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para eliminar un tlactivity
@tlactivity_bp.delete("/<id_tlactivity>")
def delete_tlactivity(id_tlactivity):
    session = None
    try:
        with get_session() as session:
            obj = session.get(TLActivity, id_tlactivity)
            if not obj:
                return jsonify({"error": "TLActivity not found"}), 404

            delete_with_retry(session, obj)

            return jsonify({"message": f"Deleted TLActivity {id_tlactivity}"}), 200

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el tlactivity porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar tlactivity: {db_error}")
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
        print(f"Error inesperado al eliminar tlactivity: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500