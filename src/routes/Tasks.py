import json
from datetime import date, timedelta
from flask import Blueprint, jsonify, request
from sqlmodel import select, or_
from ..database.db_sqlmodel import get_session
from ..models.TasksModel import Tasks, TasksCreate, TasksUpdate
from ..models.JobModel import Job, JobType
from ..models.MemberModel import Member
from ..models.SubcontractorModel import Subcontractor
from ..utils.id_generator import generate_custom_id
from sqlalchemy.orm import joinedload
from ..utils.relationships import add_relationships
from ..utils.pagination import paginate
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.auth.routes_protection import require_permission
from ..utils.middleware.logs.logs import logger
from src.utils.audit import audit

tasks_bp = Blueprint("tasks_blueprint", __name__, url_prefix="/tasks")


# ── GETs ─────────────────────────────────────────────────────────────────────

@tasks_bp.get("/")
@require_permission(["tasks:read", "tasks:read_own"])
@handle_exceptions()
@paginate()
def list_tasks():
    with get_session() as session:
        results = session.exec(
            select(Tasks).options(joinedload(Tasks.job),
                                  joinedload(Tasks.technician))
        ).unique().all()
        if not results:
            return [], 200
        return [add_relationships(t, ["job", "technician"]) for t in results], 200


@tasks_bp.get("/weekly")
@require_permission(["tasks:read", "tasks:read_own"])
@handle_exceptions()
def get_weekly_tasks():
    """
    Retorna tareas cuya Delivery_date cae dentro de la semana actual (lun–dom).
    Query param opcional: ?job_type=QID | PTL | PAR
    Incluye relaciones: job y member.
    """
    today = date.today()
    week_offset = request.args.get("week_offset", 0, type=int)
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    sunday = monday + timedelta(days=6)

    job_type_param = request.args.get("job_type", None)
    member_id_param = request.args.get("member_id", None)
    subcontractor_id_param = request.args.get("subcontractor_id", None)

    with get_session() as session:
        query = (
            select(Tasks)
            .options(
                joinedload(Tasks.job),
                joinedload(Tasks.member),
                joinedload(Tasks.subcontractor),
            )
            .where(
                or_(
                    Tasks.Designation_date <= sunday,
                    Tasks.Designation_date == None
                )
            )
            .where(
                or_(
                    Tasks.Delivery_date >= monday,
                    Tasks.Delivery_date == None
                )
            )
        )

        if member_id_param:
            query = query.where(
                or_(
                    Tasks.ID_Member == member_id_param,
                    Tasks.job.has(Job.members.any(Member.ID_Member == member_id_param))
                )
            )

        if subcontractor_id_param:
            from src.models.TechnicianModel import Technician
            query = query.where(
                or_(
                    Tasks.ID_Subcontractor == subcontractor_id_param,
                    Tasks.technician.has(Technician.ID_Subcontractor == subcontractor_id_param)
                )
            )

        if job_type_param:
            try:
                job_type_enum = JobType(job_type_param)
            except ValueError:
                raise AppException(
                    f"job_type inválido. Valores permitidos: {[e.value for e in JobType]}",
                    "invalid_job_type",
                    400
                )
            query = query.join(Tasks.job).where(Job.Job_type == job_type_enum)

        results = session.exec(query).unique().all()

        if not results:
            return [], 200

        payload = []
        for t in results:
            payload.append({
                "ID_Tasks":          t.ID_Tasks,
                "Name":              t.Name,
                "Task_description":  t.Task_description,
                "Task_status":       t.Task_status,
                "Priority":          t.Priority,
                "Designation_date":  t.Designation_date.isoformat() if t.Designation_date else None,
                "Delivery_date":     t.Delivery_date.isoformat() if t.Delivery_date else None,
                "ID_Subcontractor":  t.ID_Subcontractor,
                "job":               t.job.model_dump() if t.job else None,
                "member":            t.member.model_dump() if t.member else None,
                "subcontractor":     {
                    "ID_Subcontractor": t.subcontractor.ID_Subcontractor,
                    "Name":             t.subcontractor.Name,
                    "Organization":     t.subcontractor.Organization,
                } if t.subcontractor else None,
            })

        return payload, 200


@tasks_bp.get("/<id_tasks>")
@require_permission(["tasks:read", "tasks:read_own"])
@handle_exceptions()
def get_tasks(id_tasks):
    with get_session() as session:
        obj = session.exec(
            select(Tasks)
            .options(joinedload(Tasks.job), joinedload(Tasks.technician))
            .where(Tasks.ID_Tasks == id_tasks)
        ).unique().first()
        if not obj:
            raise AppException("Task no encontrado.", "task_not_found", 404)
        return add_relationships(obj, ["job", "technician"]), 200


@tasks_bp.get("/job/<id_jobs>/tech/<id_tech>")
@require_permission(["tasks:read", "tasks:read_own"])
@handle_exceptions()
@paginate()
def get_tasks_by_job(id_jobs, id_tech):
    with get_session() as session:
        statement = (
            select(Tasks)
            .options(joinedload(Tasks.job), joinedload(Tasks.technician))
            .where(Tasks.ID_Jobs == id_jobs)
        )
        # "ALL" = comodín del proxy del panel: todas las tareas del job
        if id_tech and id_tech.upper() != "ALL":
            statement = statement.where(Tasks.ID_Technician == id_tech)
        results = session.exec(statement).unique().all()
        if not results:
            return [], 200
        return [add_relationships(t, ["job", "technician"]) for t in results], 200


# --------------- RUTAS POST, PATCH AND DELETE----------#

@tasks_bp.post("/")
@require_permission("tasks:create")
@handle_exceptions()
@audit("Task created", entity_type="Tasks", id_from="response")
def create_tasks():
    data = request.get_json()
    create_tasks = TasksCreate.model_validate(data)
    obj = Tasks(
        **create_tasks.model_dump(exclude_unset=False, exclude_none=False))

    with get_session() as session:
        obj.ID_Tasks = generate_custom_id(session, Tasks, "ID_Tasks", "TSK")
        save_with_retry(session, obj)
        logger.info("✅ Task creada | task_id=%s", obj.ID_Tasks)
        return obj.model_dump(), 201


@tasks_bp.patch("/<task_id>")
@require_permission("tasks:update")
@handle_exceptions()
@audit("Task updated", entity_type="Tasks", id_param="task_id")
def update_tasks(task_id):
    data = request.get_json()
    with get_session() as session:
        obj = session.exec(select(Tasks).where(
            Tasks.ID_Tasks == task_id)).first()
        if not obj:
            raise AppException("Task no encontrado.", "task_not_found", 404)

        update_data = TasksUpdate.model_validate(
            data).model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(obj, key, value)
        save_with_retry(session, obj)
        logger.info("🔄 Task actualizada | task_id=%s", task_id)
        return obj.model_dump(), 200


@tasks_bp.delete("/<task_id>")
@require_permission("tasks:delete")
@handle_exceptions()
@audit("Task deleted", entity_type="Tasks", id_param="task_id")
def delete_tasks(task_id):
    with get_session() as session:
        obj = session.exec(select(Tasks).where(
            Tasks.ID_Tasks == task_id)).first()
        if not obj:
            raise AppException("Task no encontrado.", "task_not_found", 404)

        delete_with_retry(session, obj)
        logger.info("🗑️ Task eliminado | task_id=%s", task_id)
        return jsonify({"message": f"Task {task_id} eliminada correctamente"}), 200
