import json
from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.TasksModel import Tasks, TasksCreate, TasksUpdate
from ..utils.id_generator import generate_custom_id
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.relationships import add_relationships
from ..utils.pagination import paginate
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..podio.services.tasks_services import podio_tasks_router
import time
from ..utils.mapper_aux_functions import register_event
from ..utils.mappers.to_podio.tasks_mapper import map_task_to_podio


# Blueprint de Tasks:
tasks_bp = Blueprint("tasks_blueprint", __name__,
                     url_prefix="/tasks")

# -------------------RUTAS CRUD-------------------#


# Ruta para conseguir la lista de todos las tareas
@tasks_bp.get("/")
@paginate()
def list_tasks():
    try:
        with get_session() as session:
            statement = (
                select(Tasks)
                .options(
                    joinedload(Tasks.job),
                    joinedload(Tasks.technician))
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            tasks_data = [
                add_relationships(
                    tasks, ["job", "technician"])
                for tasks in results
            ]

            return tasks_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(f"Error de base de datos al listar las tareas: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Error inesperado al listar las tareas: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir una tarea por ID
@tasks_bp.get("/<id_tasks>")
def get_tasks(id_tasks):
    try:
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
                return jsonify({"error": "Task not found"}), 404

            tasks_data = add_relationships(
                obj, ["job", "technician"])

            return jsonify(tasks_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar la tarea {id_tasks}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar las tareas: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear una tarea
@tasks_bp.post("/")
def create_tasks():
    try:
        data = request.get_json()
        create_tasks = TasksCreate.model_validate(data)
        obj = Tasks(
            **create_tasks.model_dump(exclude_unset=False, exclude_none=False))

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, Tasks, "ID_Tasks", "TSK")
            obj.ID_Tasks = new_id

            save_with_retry(session, obj)

            # Mapear a Podio
            podio_fields = map_task_to_podio(obj, session=session)
            print("🚀 Payload enviado a Podio:")
            print(json.dumps(podio_fields, indent=4, ensure_ascii=False))

            podio_service = podio_tasks_router.get_service()

            try:
                podio_response = podio_service.create_item(podio_fields)

                # Guardar el podio_item_id en PostgreSQL
                if podio_response and podio_response.get("item_id"):
                    obj.podio_item_id = podio_response["item_id"]
                    # Anti-loop: registrar evento
                    register_event(obj.podio_item_id)

                    save_with_retry(session, obj)
                    print(f"✅ Job guardado en DB: {obj.podio_item_id}")

                else:
                    print("⚠️ No se pudo obtener los datos de Podio.")

            except Exception as podio_error:
                print(f"⚠️ Error al crear item en Podio: {podio_error}")

            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:  # Cuando violas una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe una tarea con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Error de base de datos al crear tarea: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Error inesperado durante la creación de la tarea: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar una tarea
@tasks_bp.patch("/<podio_item_id>")
def update_tasks(podio_item_id):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.exec(
                select(Tasks).where(Tasks.podio_item_id == podio_item_id)
            ).first()
            if not obj:
                return jsonify({"error": "Task not found"}), 404

            update_tasks = TasksUpdate.model_validate(data)
            update_data_dict = update_tasks.model_dump(
                exclude_unset=True)  # Crea dict limpio

            for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
                setattr(obj, key, value)

            save_with_retry(session, obj)

            # Mapear a Podio
            podio_service = podio_tasks_router.get_service()
            podio_fields = map_task_to_podio(obj)

            try:
                if obj.podio_item_id:
                    podio_service.update_item(
                        int(obj.podio_item_id), podio_fields)

                    # Anti-loop: registrar evento
                    register_event(obj.podio_item_id)

                    print(
                        f"🧩 Client {podio_item_id} actualizado en Podio (item_id={obj.podio_item_id})")

                else:
                    # Si no tiene podio_item_id, crearlo en Podio
                    podio_response = podio_service.create_item(podio_fields)
                    if podio_response and podio_response.get("item_id"):
                        obj.podio_item_id = podio_response["item_id"]

                        save_with_retry(session, obj)
                        print(
                            f"✅ Client {podio_item_id} creado en Podio (item_id={obj.podio_item_id})")

            except Exception as podio_error:
                print(
                    f"⚠️ Error al actualizar/crear Client en Podio: {podio_error}")

            return jsonify(obj.model_dump()), 200

    # Exceptions de errores de validacion, integridad, infraestructura o inesperado del servidor.
    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de tarea inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe una tarea con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al actualizar tarea: {db_error}")
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
        print(f"Error inesperado al actualizar tarea: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para eliminar un distruibidor

@tasks_bp.delete("/<podio_item_id>")
def delete_tasks(podio_item_id):
    session = None
    try:
        with get_session() as session:
            obj = session.exec(
                select(Tasks).where(Tasks.podio_item_id == podio_item_id)
            ).first()
            if not obj:
                return jsonify({"error": "Task not found"}), 404

            # Eliminar en Podio
            podio_service = podio_tasks_router.get_service()
            try:
                podio_service.delete_item(obj.podio_item_id)
                # Anti-loop: registrar evento
                register_event(obj.podio_item_id)
                print(f"🗑️ Tarea eliminado en Podio: {obj.podio_item_id}")
            except Exception as podio_error:
                print(f"⚠️ Error borrando tarea en Podio: {podio_error}")

            # Eliminar en DB
            delete_with_retry(session, obj)

            return jsonify({"message": f"Task {podio_item_id} eliminada correctamente"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:  # En caso de borrar una tarea que tiene productos asociados con Foreign Key
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar la tarea porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar tarea: {db_error}")
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
        print(f"Error inesperado al eliminar tarea: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
