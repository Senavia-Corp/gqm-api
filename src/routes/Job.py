# ======================================== Código para la Base de Datos en Postgresql =================================
from ..models.JobModel import (
    podio_list_jobs,
    podio_create_job_item,
    podio_update_job_item,
    podio_delete_job_item,
)
from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.JobModel import Job, JobCreate, JobUpdate
from ..utils.id_generator import generate_custom_id
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError

# Blueprint de Jobs:
job_bp = Blueprint("job_blueprint", __name__, url_prefix="/jobs")

# -------------------RUTAS CRUD-------------------#

# Ruta para conseguir la lista de todos los trabajos


@job_bp.get("/")
def list_jobs():
    try:
        with get_session() as session:
            results = session.exec(select(Job)).all()
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


# Ruta para conseguir un trabajo por ID
@job_bp.get("/<id_job>")
def get_job(id_job):
    try:
        with get_session() as session:
            obj = session.get(Job, id_job)
            if not obj:
                return jsonify({"error": "Job not found"}), 404
            return jsonify(obj.model_dump()), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar proveedor {id_job}: {db_error}")
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

# Ruta para crear un trabajo


@job_bp.post("/")  # REVISAR
def create_job():
    try:
        data = request.get_json()
        create_job = JobCreate.model_validate(data)
        obj = Job.model_validate(create_job)

    except ValidationError as e:
        # Error en el campo Job_type.
        for err in e.errors():
            if err["loc"] == ("Job_type",):
                return jsonify({
                    "detail": "El campo 'Job_type' debe ser uno de los valores permitidos: QID, PTL o PAR."
                }), 400
        # Error en otros campos o JSON.
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            prefix = obj.Job_type.upper()
            new_id = generate_custom_id(
                session, Job, "ID_Jobs", prefix)
            obj.ID_Jobs = new_id

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

# Ruta para actualizar un trabajo


@job_bp.patch("/<id_job>")
def update_job(id_job):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(Job, id_job)
            if not obj:
                return jsonify({"error": "Job not found"}), 404

            update_job = JobUpdate.model_validate(data)
            update_data_dict = update_job.model_dump(
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

# Ruta para eliminar un trabajo


@job_bp.delete("/<id_job>")
def delete_job(id_job):
    session = None
    try:
        with get_session() as session:
            obj = session.get(Job, id_job)
            if not obj:
                return jsonify({"error": "Job not found"}), 404
            session.delete(obj)
            session.commit()
            return jsonify({"message": f"Deleted Job {id_job}"}), 200

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


# =============================================== Código de para la conexión y manejo de Podio =================================


@job_bp.get("/podio/items")
def jobs_from_podio():
    """
    GET /jobs/podio/items?limit=4&format=raw|normalized|extracted
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

        data = podio_list_jobs(
            limit=limit, offset=offset, fetch_all=fetch_all, view_id=view_id,
            fmt=fmt, category_mode=category_mode
        )
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@job_bp.post("/podio/items")
def jobs_podio_create():
    """
    POST /jobs/podio/items
    Crea un ítem en el App 'Jobs' de Podio.
    Body esperado:
    {
      "fields": { "<external_id>": { ... } },
      "external_id": "opcional",
      "hook": true/false (opcional),
      "silent": true/false (opcional)
    }
    """
    try:
        body = request.get_json(force=True, silent=False)
        fields = body.get("fields")
        if not isinstance(fields, dict) or not fields:
            return jsonify({"error": "Body debe incluir 'fields' (dict) con al menos un campo."}), 400

        external_id = body.get("external_id")
        hook = bool(body.get("hook", True))
        silent = bool(body.get("silent", False))

        created = podio_create_job_item(
            fields_payload=fields, external_id=external_id, hook=hook, silent=silent)
        return jsonify(created), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@job_bp.patch("/podio/items/<int:item_id>")
def jobs_podio_update(item_id: int):
    """
    PATCH /jobs/podio/items/<item_id>
    Actualiza campos de un ítem en el App 'Jobs' de Podio.
    Body esperado:
    {
      "fields": { "<external_id>": { ... } },
      "hook": true/false (opcional),
      "silent": true/false (opcional)
    }
    """
    try:
        body = request.get_json(force=True, silent=False)
        fields = body.get("fields")
        if not isinstance(fields, dict) or not fields:
            return jsonify({"error": "Body debe incluir 'fields' (dict) con al menos un campo."}), 400

        hook = bool(body.get("hook", True))
        silent = bool(body.get("silent", False))

        updated = podio_update_job_item(
            item_id=item_id, fields_payload=fields, hook=hook, silent=silent)
        return jsonify(updated), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@job_bp.delete("/podio/items/<int:item_id>")
def jobs_podio_delete(item_id: int):
    """
    DELETE /jobs/podio/items/<item_id>
    Elimina un ítem en el App 'Jobs' de Podio.
    """
    try:
        podio_delete_job_item(item_id=item_id)
        return jsonify({"message": f"Podio Job item deleted: {item_id}"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400
