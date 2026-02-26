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


# Blueprint de Tasks:
tasks_bp = Blueprint("tasks_blueprint", __name__,
                     url_prefix="/tasks")


# -------------------RUTAS CRUD-------------------#
# Ruta para conseguir la lista de todos las tareas
@tasks_bp.get("/")
@handle_exceptions()
@paginate()
def list_tasks():
    with get_session() as session:
        statement = (
            select(Tasks)
            .options(
                joinedload(Tasks.job),
                joinedload(Tasks.technician))
        )
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        tasks_data = [
            add_relationships(
                tasks, ["job", "technician"])
            for tasks in results
        ]

        return tasks_data, 200


# Ruta para conseguir una tarea por ID
@tasks_bp.get("/<id_tasks>")
@handle_exceptions()
def get_tasks(id_tasks):
    with get_session() as session:
        statement = (
            select(Tasks)
            .options(
                joinedload(Tasks.job),
                joinedload(Tasks.technician))
            .where(Tasks.ID_Tasks == id_tasks)
        )

        obj = session.exec(statement).unique().first()

        if not obj:
            raise AppException("Task no encontrado.", "task_not_found", 404)

        tasks_data = add_relationships(
            obj, ["job", "technician"])

        return tasks_data, 200


# Ruta para conseguir tareas por trabajo y technician
@tasks_bp.get("/job/<id_jobs>/tech/<id_tech>")
@handle_exceptions()
@paginate()
def get_tasks_by_job(id_jobs, id_tech):
    with get_session() as session:
        statement = (
            select(Tasks)
            .options(
                joinedload(Tasks.job),
                joinedload(Tasks.technician))
            .where(Tasks.ID_Jobs == id_jobs)
            .where(Tasks.ID_Technician == id_tech)
        )

        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        tasks_data = [
            add_relationships(tasks, ["job", "technician"])
            for tasks in results
        ]

        return tasks_data, 200


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear una tarea
@tasks_bp.post("/")
@handle_exceptions()
def create_tasks():

    data = request.get_json()
    create_tasks = TasksCreate.model_validate(data)
    obj = Tasks(
        **create_tasks.model_dump(exclude_unset=False, exclude_none=False))

    with get_session() as session:
        new_id = generate_custom_id(
            session, Tasks, "ID_Tasks", "TSK")
        obj.ID_Tasks = new_id

        save_with_retry(session, obj)

        logger.info(
            "✅ Task creada | task_id=%s",
            obj.ID_Tasks
        )

        return obj.model_dump(), 201


# Ruta para actualizar una tarea
@tasks_bp.patch("/<task_id>")
@handle_exceptions()
def update_tasks(task_id):
    data = request.get_json()
    with get_session() as session:
        obj = session.exec(
            select(Tasks).where(Tasks.ID_Tasks == task_id)
        ).first()

        if not obj:
            raise AppException("Task no encontrado.", "task_not_found", 404)

        update_tasks = TasksUpdate.model_validate(data)
        update_data_dict = update_tasks.model_dump(exclude_unset=True)

        for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
            setattr(obj, key, value)

        save_with_retry(session, obj)

        logger.info("🔄 Task actualizada | task_id=%s", task_id)

        return obj.model_dump(), 200


# Ruta para eliminar una tarea
@tasks_bp.delete("/<task_id>")
@handle_exceptions()
def delete_tasks(task_id):
    with get_session() as session:
        obj = session.exec(
            select(Tasks).where(Tasks.ID_Tasks == task_id)
        ).first()
        if not obj:
            raise AppException("Task no encontrado.", "task_not_found", 404)

        delete_with_retry(session, obj)

        logger.info("🗑️ Task eliminado | task_id=%s", task_id)

        return jsonify({"message": f"Task {task_id} eliminada correctamente"}), 200
