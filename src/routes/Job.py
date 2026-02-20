# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.JobModel import Job, JobCreate, JobUpdate
from ..models.MemberModel import Member
from ..models.ClientModel import Client
from ..models.SubcontractorModel import Subcontractor
from ..models.link_models.JobMember import JobMemberLink
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload, selectinload, load_only
from sqlalchemy import func, extract, or_, and_
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..podio.services.job_services import podio_jobs_router
from ..utils.mappers.mapper_aux_functions import register_event
from ..utils.mappers.to_podio.qid_mapper import map_job_to_podio_qid
from ..utils.mappers.to_podio.ptl_mapper import map_job_to_podio_ptl
from ..utils.mappers.to_podio.par_mapper import map_job_to_podio_par


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
                    joinedload(Job.tasks),
                    joinedload(Job.estimate_costs),
                    joinedload(Job.payment_units),
                    joinedload(Job.subcontractors).joinedload(
                        Subcontractor.technicians),
                    joinedload(Job.subcontractors).joinedload(
                        Subcontractor.orders),
                    joinedload(Job.tlactivity),
                    joinedload(Job.change_orders),
                    joinedload(Job.building_dept),
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404   # El decorador se encarga del formato final

            # Traer los roles de members
            job_ids = [job.ID_Jobs for job in results]

            roles_statement = (
                select(JobMemberLink)
                .where(JobMemberLink.job_id.in_(job_ids))
            )

            roles = session.exec(roles_statement).all()
            roles_map = {
                (link.job_id, link.member_id): link.rol
                for link in roles
            }

            jobs_data = []

            for job in results:
                job_dict = add_relationships(
                    job, ["client", "members", "multipliers", "building_dept", "change_orders",
                          "attachments", "subcontractors.technicians", "tasks", "tlactivity",
                          "subcontractors.orders", "estimate_costs", "payment_units"],)

                for member in job_dict.get("members", []):
                    key = (job.ID_Jobs, member["ID_Member"])
                    member["rol"] = roles_map.get(key)

                jobs_data.append(job_dict)

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


@job_bp.get("/jobs_table")
def list_jobs_table():
    try:
        # params
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 10))
        if page < 1:
            page = 1
        if limit < 1:
            limit = 10
        # opcional: cap para evitar abusos
        limit = min(limit, 200)

        job_type = request.args.get("type")      # QID/PTL/PAR
        status = request.args.get("status")      # "PAID", "Archived", etc
        year = request.args.get("year")          # 2023/2024/2025/2026

        # normalizar type si llega
        if job_type:
            job_type = job_type.upper()

        year_int = None
        if year:
            try:
                year_int = int(year)
            except ValueError:
                return jsonify({"detail": "Invalid year"}), 400

        with get_session() as session:
            # -----------------------------
            # Base query (solo columnas tabla)
            # -----------------------------
            statement = (
                select(Job)
                .options(
                    load_only(
                        Job.ID_Jobs,
                        Job.Job_type,
                        Job.Project_name,
                        Job.Project_location,
                        Job.Job_status,
                        Job.Date_assigned,
                        Job.Gqm_formula_pricing,
                        Job.ID_Client,
                        Job.Estimated_start_date
                    ),
                    selectinload(Job.client).load_only(
                        Client.ID_Client,
                        Client.Client_Community,
                    ),
                    selectinload(Job.members).load_only(
                        Member.ID_Member,
                        Member.Member_Name,
                    ),
                )
            )

            # -----------------------------
            # Filters
            # -----------------------------
            if job_type:
                statement = statement.where(Job.Job_type == job_type)

            if status:
                statement = statement.where(Job.Job_status == status)

            if year_int is not None:
                # ✅ Year filter "aware" por tipo:
                # - PTL usa Estimated_start_date
                # - QID/PAR usan Date_assigned
                # - ALL (sin type) combina ambos en un OR
                if job_type == "PTL":
                    statement = statement.where(
                        Job.Estimated_start_date.is_not(None),
                        extract("year", Job.Estimated_start_date) == year_int,
                    )
                elif job_type:
                    statement = statement.where(
                        Job.Date_assigned.is_not(None),
                        extract("year", Job.Date_assigned) == year_int,
                    )
                else:
                    statement = statement.where(
                        or_(
                            and_(
                                Job.Job_type == "PTL",
                                Job.Estimated_start_date.is_not(None),
                                extract("year", Job.Estimated_start_date) == year_int,
                            ),
                            and_(
                                Job.Job_type != "PTL",
                                Job.Date_assigned.is_not(None),
                                extract("year", Job.Date_assigned) == year_int,
                            ),
                        )
                    )

            # -----------------------------
            # Total count (sin options/loads)
            # -----------------------------
            count_stmt = select(func.count()).select_from(Job)

            if job_type:
                count_stmt = count_stmt.where(Job.Job_type == job_type)
            if status:
                count_stmt = count_stmt.where(Job.Job_status == status)

            if year_int is not None:
                if job_type == "PTL":
                    count_stmt = count_stmt.where(
                        Job.Estimated_start_date.is_not(None),
                        extract("year", Job.Estimated_start_date) == year_int,
                    )
                elif job_type:
                    count_stmt = count_stmt.where(
                        Job.Date_assigned.is_not(None),
                        extract("year", Job.Date_assigned) == year_int,
                    )
                else:
                    count_stmt = count_stmt.where(
                        or_(
                            and_(
                                Job.Job_type == "PTL",
                                Job.Estimated_start_date.is_not(None),
                                extract("year", Job.Estimated_start_date) == year_int,
                            ),
                            and_(
                                Job.Job_type != "PTL",
                                Job.Date_assigned.is_not(None),
                                extract("year", Job.Date_assigned) == year_int,
                            ),
                        )
                    )

            total = session.exec(count_stmt).one()

            # -----------------------------
            # Pagination SQL
            # -----------------------------
            offset = (page - 1) * limit
            statement = (
                statement
                .order_by(Job.ID_Jobs.desc())  # o Date_assigned.desc() si prefieres
                .offset(offset)
                .limit(limit)
            )

            results = session.exec(statement).unique().all()

            if not results:
                return jsonify({
                    "page": page,
                    "limit": limit,
                    "total": total,
                    "results": []
                }), 200

            # -----------------------------
            # Roles de members (solo para los jobs de esta página)
            # -----------------------------
            job_ids = [j.ID_Jobs for j in results if j.ID_Jobs]
            roles = session.exec(
                select(JobMemberLink).where(JobMemberLink.job_id.in_(job_ids))
            ).all()
            roles_map = {(l.job_id, l.member_id): l.rol for l in roles}

            # -----------------------------
            # Serialización "light" (sin add_relationships heavy)
            # -----------------------------
            out = []
            for j in results:
                j_dict = {
                    "ID_Jobs": j.ID_Jobs,
                    "Job_type": j.Job_type,
                    "Project_name": j.Project_name,
                    "Project_location": j.Project_location,
                    "Job_status": j.Job_status,
                    "Date_assigned": j.Date_assigned,
                    "Estimated_start_date": j.Estimated_start_date,
                    "Gqm_formula_pricing": j.Gqm_formula_pricing,
                    "client": None,
                    "members": [],
                }

                if j.client:
                    j_dict["client"] = {
                        "ID_Client": j.client.ID_Client,
                        "Client_Community": getattr(j.client, "Client_Community", None),
                    }

                for m in (j.members or []):
                    j_dict["members"].append({
                        "ID_Member": m.ID_Member,
                        "Member_Name": getattr(m, "Member_Name", None),
                        "rol": roles_map.get((j.ID_Jobs, m.ID_Member)),
                    })

                out.append(j_dict)

            return jsonify({
                "page": page,
                "limit": limit,
                "total": total,
                "results": out
            }), 200

    except Exception as e:
        print(f"Error jobs_table: {e}")
        return jsonify({
            "detail": "Error interno del servidor.",
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
                    joinedload(Job.tasks),
                    joinedload(Job.estimate_costs),
                    joinedload(Job.payment_units),
                    joinedload(Job.subcontractors).joinedload(
                        Subcontractor.technicians),
                    joinedload(Job.subcontractors).joinedload(
                        Subcontractor.orders),
                    joinedload(Job.tlactivity),
                    joinedload(Job.change_orders),
                    joinedload(Job.building_dept),
                )
                .where(Job.ID_Jobs == id_job)
            )
            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "Job not found"}), 404

            # Busca y relaciona el rol correspondiente
            roles_statement = (
                select(JobMemberLink)
                .where(JobMemberLink.job_id == obj.ID_Jobs)
            )
            roles = session.exec(roles_statement).all()
            roles_map = {
                link.member_id: link.rol
                for link in roles
            }

            job_data = add_relationships(
                obj,  ["client", "members", "multipliers", "building_dept", "change_orders",
                       "attachments", "subcontractors.technicians", "tasks", "tlactivity",
                       "subcontractors.orders", "estimate_costs", "payment_units"])

            # Agregar rol a los members
            for member in job_data.get("members", []):
                member_id = member["ID_Member"]
                member["rol"] = roles_map.get(member_id)

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


# Ruta para conseguir un trabajo por tipo y por año
@job_bp.get("/by-type-year")
@paginate()
def get_jobs_by_type_year():
    try:
        job_type = request.args.get("type")   # PTL, PAR, QID
        year = request.args.get("year")       # 2025, 2024, 2023

        if not job_type or not year:
            return jsonify({"error": "Debes enviar type y year"}), 400

        # Extraemos el último dígito del año (tu lógica actual)
        year_digit = year[-1]  # 2025 -> "5"
        pattern = f"{job_type.upper()}{year_digit}%"

        with get_session() as session:
            statement = (
                select(Job)
                .options(
                    joinedload(Job.client),
                    joinedload(Job.members),
                    joinedload(Job.multipliers),
                    joinedload(Job.attachments),
                    joinedload(Job.tasks),
                    joinedload(Job.estimate_costs),
                    joinedload(Job.payment_units),
                    joinedload(Job.subcontractors).joinedload(
                        Subcontractor.technicians),
                    joinedload(Job.subcontractors).joinedload(
                        Subcontractor.orders),
                    joinedload(Job.tlactivity),
                    joinedload(Job.change_orders),
                    joinedload(Job.building_dept),
                )
                .where(Job.ID_Jobs.like(pattern))
            )

            results = session.exec(statement).unique().all()

            if not results:
                return [], 404   # El decorador se encarga del formato final

            # Traer los roles de members
            job_ids = [job.ID_Jobs for job in results]

            roles_statement = (
                select(JobMemberLink)
                .where(JobMemberLink.job_id.in_(job_ids))
            )

            roles = session.exec(roles_statement).all()
            roles_map = {
                (link.job_id, link.member_id): link.rol
                for link in roles
            }

            jobs_data = []

            for job in results:
                job_dict = add_relationships(
                    job, ["client", "members", "multipliers", "building_dept", "change_orders",
                          "attachments", "subcontractors.technicians", "tasks", "tlactivity",
                          "subcontractors.orders", "estimate_costs", "payment_units"],)

                for member in job_dict.get("members", []):
                    key = (job.ID_Jobs, member["ID_Member"])
                    member["rol"] = roles_map.get(key)

                jobs_data.append(job_dict)

            return jobs_data, 200

    except SQLAlchemyError as db_error:
        print(f"Error de base de datos al listar trabajos: {db_error}")
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
                .join(Job.members)
                .options(
                    joinedload(Job.client),
                    joinedload(Job.members),
                    joinedload(Job.multipliers),
                    joinedload(Job.attachments),
                    joinedload(Job.subcontractors)
                    .joinedload(Subcontractor.technicians)
                )
                .where(Member.ID_Member == id_member)
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
        print(f"Error inesperado al listar trabajos por member: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un trabajo por ID_Subcontractor
@job_bp.get("/subcontractor/<id_subcontractor>")
@paginate()
def get_job_by_subcontrID(id_subcontractor):
    try:
        with get_session() as session:
            statement = (
                select(Job)
                .join(Job.subcontractors)
                .options(
                    joinedload(Job.client),
                    joinedload(Job.members),
                    joinedload(Job.multipliers),
                    joinedload(Job.attachments),
                    joinedload(Job.subcontractors)
                    .joinedload(Subcontractor.technicians)
                )
                .where(Subcontractor.ID_Subcontractor == id_subcontractor)
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
        print(f"Error inesperado al listar trabajos por subcontratista: {e}")
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
            # Mapeador segun Job type
            if obj.Job_type == "QID":
                podio_fields = map_job_to_podio_qid(obj, session=session)
            elif obj.Job_type == "PTL":
                podio_fields = map_job_to_podio_ptl(obj, session=session)
            elif obj.Job_type == "PAR":
                podio_fields = map_job_to_podio_par(obj, session=session)
            else:
                return jsonify({"error": f"Job_type inválido: {obj.Job_type}"}), 400

            # Crear también en Podio
            podio_service = podio_jobs_router.get_service(obj.Job_type)

            try:
                # 🔹 Loggear payload antes de enviarlo
                import json
                print("🚀 Payload que se enviará a Podio:")
                print(json.dumps(podio_fields, indent=4))

                podio_response = podio_service.create_item(podio_fields)

                # Guardar el podio_item_id en PostgreSQL
                if podio_response and podio_response.get("item_id"):
                    obj.podio_item_id = podio_response["item_id"]

                    # Buscar y guardar el ID_Jobs
                    item = podio_service.get_item(obj.podio_item_id)
                    formatted_id = item.get("app_item_id_formatted")
                    if formatted_id:
                        obj.ID_Jobs = formatted_id
                    else:
                        raise ValueError(
                            "No se pudo obtener app_item_id_formatted de Podio")

                    # Anti-loop: registrar evento
                    register_event(obj.podio_item_id)

                    save_with_retry(session, obj)

                else:
                    print("⚠️ No se pudo obtener los datos de Podio.")

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

            # Mapeador segun Job type
            if obj.Job_type == "QID":
                podio_fields = map_job_to_podio_qid(obj, session=session)
            elif obj.Job_type == "PTL":
                podio_fields = map_job_to_podio_ptl(obj, session=session)
            elif obj.Job_type == "PAR":
                podio_fields = map_job_to_podio_par(obj, session=session)
            else:
                return jsonify({"error": f"Job_type inválido: {obj.Job_type}"}), 400

            podio_service = podio_jobs_router.get_service(obj.Job_type)

            # Actualizar también en Podio
            try:
                if obj.podio_item_id:
                    podio_service.update_item(
                        int(obj.podio_item_id), podio_fields)
                    # Anti-loop: registrar evento
                    register_event(obj.podio_item_id)

                    save_with_retry(session, obj)
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

            podio_service = podio_jobs_router.get_service(obj.Job_type)

            # Eliminar también en Podio
            try:
                podio_service.delete_item(obj.podio_item_id)
                # Anti-loop: registrar evento
                register_event(obj.podio_item_id)

            except Exception as e:
                print("⚠️ Error borrando en Podio:", e)

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
