# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.JobModel import Job, JobCreate, JobUpdate
from ..utils.id_generator import generate_custom_id
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError

from ..podio.services.job_services import (
    create_podio_job,
    update_podio_job,
    delete_podio_job
)

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
        print(f"Error de base de datos al listar trabajos: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Error inesperado al listar trabajos: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un trabajo por ID_Jobs
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
            f"Error de base de datos al buscar trabajo {id_job}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar trabajos: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para crear un trabajo
@job_bp.post("/")
def create_job():
    session = None
    try:
        data = request.get_json()
        job_data = JobCreate.model_validate(data)
        obj = Job.model_validate(job_data)

        with get_session() as session:
            prefix = obj.Job_type.upper()
            new_id = generate_custom_id(session, Job, "ID_Jobs", prefix)
            obj.ID_Jobs = new_id

            # Guardar en base de datos
            session.add(obj)
            session.commit()
            session.refresh(obj)

            # Crear también en Podio
            try:
                podio_fields = {
                    "id-projects-workorder": obj.ID_Jobs,                # ID Projects & Workorder
                    "project-location": obj.Project_location,            # Project Location
                    "job-status": obj.Job_status,                        # Job Status
                    "project-name-2": obj.Project_name,                  # Project Name - Community
                    "powtnwo": obj.Po_wtn_wo,                            # PO/WTN/WO#
                    "service-type": obj.Service_type,                    # Service Type
                    "date-assigned": obj.Date_assigned,                  # Date Assigned
                    # GQM (Adj Formula) Pricing
                    "gqm-adj-formula-pricing": obj.Gqm_adj_formula_pricing,
                    # GQM (Target) Sold Pricing
                    "gqm-target-sold-pricing": obj.Gqm_target_sold_pricing,
                    # 2025 GQM (Premium in $)
                    "2023-gqm-final": obj.Gqm_premium_in_money,
                    # GQM (Final Sold) Pricing
                    "2023-gqm-premium-in": obj.Gqm_final_sold_pricing,
                    # GQM (Final) %
                    "gqm-final-sold-pricing": obj.Gqm_final_percentage,
                    "gqm-total-change-orders": obj.Gqm_total_change_orders,   # GQM Total Change Orders
                }

                podio_response = create_podio_job(podio_fields)

                # Guardar el podio_item_id en PostgreSQL
                if podio_response and podio_response.get("item_id"):
                    job_obj = session.get(Job, obj.ID_Jobs)
                    job_obj.podio_item_id = podio_response["item_id"]
                    session.add(job_obj)
                    session.commit()
                    print(
                        f"✅ Guardado podio_item_id: {job_obj.podio_item_id}")
                else:
                    print("⚠️ No se pudo obtener el item_id de Podio.")

            except Exception as podio_error:
                print(f"⚠️ Error al crear item en Podio: {podio_error}")

            return jsonify(obj.model_dump()), 201

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

    except IntegrityError as e:  # Cuando violas una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un trabajo con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Error de base de datos al crear trabajo: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Error inesperado durante la creación de trabajo: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar un trabajo
@job_bp.patch("/<podio_item_id>")
def update_job(podio_item_id):
    session = None
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.exec(select(Job).where(
                Job.podio_item_id == podio_item_id)).first()
            if not obj:
                return jsonify({"error": "Job not found"}), 404

            update_job = JobUpdate.model_validate(data)
            update_data = update_job.model_dump(exclude_unset=True)

            for key, value in update_data.items():
                setattr(obj, key, value)

            session.add(obj)
            session.commit()
            session.refresh(obj)

            # Actualizar también en Podio
            try:
                podio_fields = {
                    "id-projects-workorder": obj.ID_Jobs,                # ID Projects & Workorder
                    "project-location": obj.Project_location,            # Project Location
                    "job-status": obj.Job_status,                        # Job Status
                    "project-name-2": obj.Project_name,                  # Project Name - Community
                    "powtnwo": obj.Po_wtn_wo,                            # PO/WTN/WO#
                    "service-type": obj.Service_type,                    # Service Type
                    "date-assigned": obj.Date_assigned,                  # Date Assigned
                    # GQM (Adj Formula) Pricing
                    "gqm-adj-formula-pricing": obj.Gqm_adj_formula_pricing,
                    # GQM (Target) Sold Pricing
                    "gqm-target-sold-pricing": obj.Gqm_target_sold_pricing,
                    # 2025 GQM (Premium in $)
                    "2023-gqm-final": obj.Gqm_premium_in_money,
                    # GQM (Final Sold) Pricing
                    "2023-gqm-premium-in": obj.Gqm_final_sold_pricing,
                    # GQM (Final) %
                    "gqm-final-sold-pricing": obj.Gqm_final_percentage,
                    "gqm-total-change-orders": obj.Gqm_total_change_orders,   # GQM Total Change Orderss
                }
                if obj.podio_item_id:
                    update_podio_job(int(obj.podio_item_id), podio_fields)
                    print(
                        f"🧩 Job {podio_item_id} actualizado en Podio (item_id={obj.podio_item_id})")
                else:
                    print(
                        f"⚠️ Job {podio_item_id} no tiene podio_item_id, se omitió actualización en Podio")

            except Exception as podio_error:
                print(f"⚠️ Error al actualizar item en Podio: {podio_error}")

            return jsonify(obj.model_dump()), 200

    # Exceptions de errores de validacion, integridad, infraestructura o inesperado del servidor.
    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de trabajo inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un trabajos con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al actualizar trabajo: {db_error}")
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
        print(f"Error inesperado al actualizar trabajo: {e}")
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

            # Eliminar también en Podio
            if obj.podio_item_id:
                try:
                    delete_podio_job(obj.podio_item_id)
                except Exception as podio_error:
                    print(f"⚠️ Error al eliminar item en Podio: {podio_error}")

            session.delete(obj)
            session.commit()

            return jsonify({"message": f"Job {id_job} eliminado correctamente"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:  # En caso de borrar un trabajo que tiene productos asociados con Foreign Key
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el trabajo porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar trabajo: {db_error}")
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
        print(f"Error inesperado al eliminar trabajo: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
