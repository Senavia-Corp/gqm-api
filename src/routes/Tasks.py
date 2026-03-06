import json
from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.TasksModel import Tasks, TasksCreate, TasksUpdate
from ..utils.id_generator import generate_custom_id
from sqlalchemy.orm import joinedload
from ..utils.relationships import add_relationships
from ..utils.pagination import paginate
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger
from src.utils.audit import audit   # ← NEW

tasks_bp = Blueprint("tasks_blueprint", __name__, url_prefix="/tasks")


# ── GETs (unchanged) ─────────────────────────────────────────────────────────

@tasks_bp.get("/")
@handle_exceptions()
@paginate()
def list_tasks():
    with get_session() as session:
        results = session.exec(
            select(Tasks).options(joinedload(Tasks.job), joinedload(Tasks.technician))
        ).unique().all()
        if not results: return [], 200
        return [add_relationships(t, ["job", "technician"]) for t in results], 200


@tasks_bp.get("/<id_tasks>")
@handle_exceptions()
def get_tasks(id_tasks):
    with get_session() as session:
        obj = session.exec(
            select(Tasks)
            .options(joinedload(Tasks.job), joinedload(Tasks.technician))
            .where(Tasks.ID_Tasks == id_tasks)
        ).unique().first()
        if not obj: raise AppException("Task no encontrado.", "task_not_found", 404)
        return add_relationships(obj, ["job", "technician"]), 200


@tasks_bp.get("/job/<id_jobs>/tech/<id_tech>")
@handle_exceptions()
@paginate()
def get_tasks_by_job(id_jobs, id_tech):
    with get_session() as session:
        results = session.exec(
            select(Tasks)
            .options(joinedload(Tasks.job), joinedload(Tasks.technician))
            .where(Tasks.ID_Jobs == id_jobs)
            .where(Tasks.ID_Technician == id_tech)
        ).unique().all()
        if not results: return [], 200
        return [add_relationships(t, ["job", "technician"]) for t in results], 200


# ── WRITE routes — @audit applied ────────────────────────────────────────────
# Note: Tasks use ID_Tasks (not ID_Jobs) as primary URL param.
# job_id_from="body" because Tasks body always includes ID_Jobs.

@tasks_bp.post("/")
@handle_exceptions()
@audit("Task created", job_id_from="body")
def create_tasks():
    data         = request.get_json()
    create_tasks = TasksCreate.model_validate(data)
    obj          = Tasks(**create_tasks.model_dump(exclude_unset=False, exclude_none=False))

    with get_session() as session:
        obj.ID_Tasks = generate_custom_id(session, Tasks, "ID_Tasks", "TSK")
        save_with_retry(session, obj)
        logger.info("✅ Task creada | task_id=%s", obj.ID_Tasks)
        return obj.model_dump(), 201


@tasks_bp.patch("/<task_id>")
@handle_exceptions()
@audit("Task updated", id_param="task_id", job_id_from="response")
def update_tasks(task_id):
    data = request.get_json()
    with get_session() as session:
        obj = session.exec(select(Tasks).where(Tasks.ID_Tasks == task_id)).first()
        if not obj: raise AppException("Task no encontrado.", "task_not_found", 404)

        update_data = TasksUpdate.model_validate(data).model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(obj, key, value)
        save_with_retry(session, obj)
        logger.info("🔄 Task actualizada | task_id=%s", task_id)
        return obj.model_dump(), 200


@tasks_bp.delete("/<task_id>")
@handle_exceptions()
@audit("Task deleted", id_param="task_id", job_id_from="response")
def delete_tasks(task_id):
    with get_session() as session:
        obj = session.exec(select(Tasks).where(Tasks.ID_Tasks == task_id)).first()
        if not obj: raise AppException("Task no encontrado.", "task_not_found", 404)

        delete_with_retry(session, obj)
        logger.info("🗑️ Task eliminado | task_id=%s", task_id)
        return jsonify({"message": f"Task {task_id} eliminada correctamente"}), 200