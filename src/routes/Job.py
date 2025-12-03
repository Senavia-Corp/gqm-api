# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.JobModel import Job, JobCreate, JobUpdate
from ..models.SubcontractorModel import Subcontractor
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry

from ..podio.services.job_services import (
    create_podio_job,
    update_podio_job,
    delete_podio_job
)

# Blueprint de Jobs:
job_bp = Blueprint("job_blueprint", __name__, url_prefix="/jobs")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los trabajos
@job_bp.get("/")
@paginate()  # decorador de paginación
def list_jobs():
    try:
        with get_session() as session:
            # Trae los Jobs con la información asociada en una sola consulta
            statement = (
                select(Job)
                .options(
                    joinedload(Job.client),
                    joinedload(Job.members),
                    joinedload(Job.multipliers),
                    joinedload(Job.attachments),
                    joinedload(Job.subcontractors)
                    .joinedload(Subcontractor.technicians)
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404   # El decorador se encarga del formato final

            jobs_data = [
                # se agrega la relacion FK
                add_relationships(
                    job, ["client", "members", "multipliers", "attachments", "subcontractors.technicians"])
                for job in results
            ]

            return jobs_data, 200

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
def get_job_by_id(id_job):
    try:
        with get_session() as session:
            statement = (
                select(Job)
                .options(
                    joinedload(Job.client),
                    joinedload(Job.members),
                    joinedload(Job.multipliers),
                    joinedload(Job.attachments),
                    joinedload(Job.subcontractors)
                    .joinedload(Subcontractor.technicians)
                )
                .where(Job.ID_Jobs == id_job)
            )
            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "Job not found"}), 404

            job_data = add_relationships(
                obj, ["client", "members", "multipliers", "attachments", "subcontractors.technicians"])

            # Elimina las FK del JSON (estética)
            job_data.pop("ID_Client", None)

            return jsonify(job_data), 200

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


# Ruta para conseguir un trabajo por Job_status
@job_bp.get("/status/<status>")
@paginate()
def list_jobs_by_status(status):
    try:
        with get_session() as session:
            statement = (
                select(Job)
                .options(
                    joinedload(Job.client),
                    joinedload(Job.members),
                    joinedload(Job.multipliers),
                    joinedload(Job.attachments),
                    joinedload(Job.subcontractors)
                    .joinedload(Subcontractor.technicians)
                )
                .where(Job.Job_status == status)
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            jobs_data = [
                add_relationships(job, [
                                  "client", "members", "multipliers", "attachments", "subcontractors.technicians"])
                for job in results
            ]

            return jobs_data, 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar trabajo: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar trabajos por status: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un trabajo por ID_Client
@job_bp.get("/client/<id_client>")
@paginate()
def get_job_by_clientID(id_client):
    try:
        with get_session() as session:
            statement = (
                select(Job)
                .options(
                    joinedload(Job.client),
                    joinedload(Job.members),
                    joinedload(Job.multipliers),
                    joinedload(Job.attachments),
                    joinedload(Job.subcontractors)
                    .joinedload(Subcontractor.technicians)
                )
                .where(Job.ID_Client == id_client)
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            jobs_data = [
                add_relationships(job, [
                                  "client", "members", "multipliers", "attachments", "subcontractors.technicians"])
                for job in results
            ]

            return jobs_data, 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar trabajo: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar trabajos por cliente: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un trabajo por ID_Member
@job_bp.get("/member/<id_member>")
@paginate()
def get_job_by_memberID(id_member):
    try:
        with get_session() as session:
            statement = (
                select(Job)
                .options(
                    joinedload(Job.client),
                    joinedload(Job.members),
                    joinedload(Job.multipliers),
                    joinedload(Job.attachments),
                    joinedload(Job.subcontractors)
                    .joinedload(Subcontractor.technicians)
                )
                .where(Job.ID_Member == id_member)
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            jobs_data = [
                add_relationships(job, [
                                  "client", "members", "multipliers", "attachments", "subcontractors.technicians"])
                for job in results
            ]

            return jobs_data, 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar trabajo: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar trabajos por cliente: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un trabajo por Job_type
@job_bp.get("/type/<type>")
@paginate()
def list_jobs_by_type(type):
    try:
        with get_session() as session:
            statement = (
                select(Job)
                .options(
                    joinedload(Job.client),
                    joinedload(Job.members),
                    joinedload(Job.multipliers),
                    joinedload(Job.attachments),
                    joinedload(Job.subcontractors)
                    .joinedload(Subcontractor.technicians)
                )
                .where(Job.Job_type == type)
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            jobs_data = [
                add_relationships(job, [
                                  "client", "members", "multipliers", "attachments", "subcontractors.technicians"])
                for job in results
            ]

            return jobs_data, 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar trabajo: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar trabajos por tipo: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un trabajo por Date_assigned
@job_bp.get("/date_assigned/<date>")
@paginate()
def list_jobs_by_date(date):
    try:
        with get_session() as session:
            statement = (
                select(Job)
                .options(
                    joinedload(Job.client),
                    joinedload(Job.members),
                    joinedload(Job.multipliers),
                    joinedload(Job.attachments),
                    joinedload(Job.subcontractors)
                    .joinedload(Subcontractor.technicians)
                )
                .where(Job.Date_assigned == date)
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            jobs_data = [
                add_relationships(job, [
                                  "client", "members", "multipliers", "attachments", "subcontractors.technicians"])
                for job in results
            ]

            return jobs_data, 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar trabajo: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar trabajos por fecha: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un trabajo
@job_bp.post("/")
def create_job():
    session = None
    try:
        data = request.get_json()
        job_data = JobCreate.model_validate(data)
        obj = Job(**job_data.model_dump(exclude_unset=False, exclude_none=False))

        with get_session() as session:
            prefix = obj.Job_type.upper()
            new_id = generate_custom_id(session, Job, "ID_Jobs", prefix)
            obj.ID_Jobs = new_id

            # Guardar en base de datos
            save_with_retry(session, obj)

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
                    # GQM (Target) Return %
                    "gqm-target-return": obj.Gqm_target_return,
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
                    obj.podio_item_id = podio_response["item_id"]
                    save_with_retry(session, obj)
                    print(f"✅ Guardado podio_item_id: {obj.podio_item_id}")
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

            save_with_retry(session, obj)

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
                    # GQM (Target) Return %
                    "gqm-target-return": obj.Gqm_target_return,
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
@job_bp.delete("/<podio_item_id>")
def delete_job(podio_item_id):
    session = None
    try:
        with get_session() as session:
            obj = session.exec(select(Job).where(
                Job.podio_item_id == podio_item_id)).first()
            if not obj:
                return jsonify({"error": "Job not found"}), 404

            # Eliminar también en Podio
            if obj.podio_item_id:
                try:
                    delete_podio_job(obj.podio_item_id)
                except Exception as podio_error:
                    print(f"⚠️ Error al eliminar item en Podio: {podio_error}")

            delete_with_retry(session, obj)

            return jsonify({"message": f"Job {podio_item_id} eliminado correctamente"}), 200

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
