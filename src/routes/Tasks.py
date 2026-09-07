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
from ..utils.portal_redaction import acotar_job_para_portal, llamante_es_portal
from ..utils.pagination import paginate
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.auth.routes_protection import (
    require_permission,
    job_belongs_to_portal_user,
    portal_owns_technician,
    scope_tasks_statement,
    task_belongs_to_portal_user,
)
from ..utils.middleware.logs.logs import logger
from src.utils.audit import audit

tasks_bp = Blueprint("tasks_blueprint", __name__, url_prefix="/tasks")


# ── GETs ─────────────────────────────────────────────────────────────────────

@tasks_bp.get("/")
@require_permission("tasks:read")
@handle_exceptions()
@paginate()
def list_tasks():
    with get_session() as session:
        statement = select(Tasks).options(
            joinedload(Tasks.job), joinedload(Tasks.technician))
        # Portal: solo SUS tareas (hallazgo crítico de cobertura B7)
        statement = scope_tasks_statement(statement)
        results = session.exec(statement).unique().all()
        if not results:
            return [], 200
        return [add_relationships(t, ["job", "technician"]) for t in results], 200


@tasks_bp.get("/weekly")
@require_permission("tasks:read")
@handle_exceptions()
def get_weekly_tasks():
    """
    Retorna las tareas que SOLAPAN con la semana pedida (lun–dom).

    Ojo: el WHERE incluye los NULL a propósito, así que una tarea sin fechas
    aparece en TODAS las semanas (T-20). El docstring anterior decía
    "Delivery_date cae dentro de la semana", que no es lo que hace el código.

    Query params: ?week_offset= &job_type=QID|PTL|PAR &member_id= 
    &subcontractor_id= &technician_id=
    Incluye relaciones: job y member.
    """
    today = date.today()
    week_offset = request.args.get("week_offset", 0, type=int)
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    sunday = monday + timedelta(days=6)

    job_type_param = request.args.get("job_type", None)
    member_id_param = request.args.get("member_id", None)
    subcontractor_id_param = request.args.get("subcontractor_id", None)
    # T-06: el panel enviaba technician_id desde weekly/route.ts:41 y aquí no se
    # leía nunca, así que filtrar por técnico devolvía TODO sin avisar.
    technician_id_param = request.args.get("technician_id", None)

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
        query = scope_tasks_statement(query)

        if member_id_param:
            query = query.where(
                or_(
                    Tasks.ID_Member == member_id_param,
                    Tasks.job.has(Job.members.any(Member.ID_Member == member_id_param))
                )
            )

        if technician_id_param:
            query = query.where(Tasks.ID_Technician == technician_id_param)

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
                # T-06: sin esto el panel no puede mostrar de quién es la tarea
                # aunque ya sepa filtrarla por técnico.
                "ID_Technician":     t.ID_Technician,
                # Este handler arma el diccionario A MANO, asi que NO pasa por
                # `add_relationships` y la redaccion central no lo alcanzaba:
                # medido, /tasks/weekly entregaba al subcontratista el bloque
                # financiero entero del job (Gqm_formula_pricing,
                # Gqm_target_return, Acc_receivable, Gqm_final_sold_pricing).
                # `acotar_job_para_portal` es no-op para el staff.
                "job":               acotar_job_para_portal(
                                        t.job.model_dump(mode="json")) if t.job else None,
                # El `member` es personal interno de GQM, con su correo. Un rol
                # de portal no tiene por que recibir su ficha: solo su nombre.
                "member":            (
                    {"ID_Member": t.member.ID_Member,
                     "Member_Name": t.member.Member_Name}
                    if llamante_es_portal()
                    else t.member.model_dump()
                ) if t.member else None,
                "subcontractor":     {
                    "ID_Subcontractor": t.subcontractor.ID_Subcontractor,
                    "Name":             t.subcontractor.Name,
                    "Organization":     t.subcontractor.Organization,
                } if t.subcontractor else None,
            })

        return payload, 200


@tasks_bp.get("/<id_tasks>")
@require_permission("tasks:read")
@handle_exceptions()
def get_tasks(id_tasks):
    with get_session() as session:
        obj = session.exec(
            select(Tasks)
            .options(joinedload(Tasks.job), joinedload(Tasks.technician))
            .where(Tasks.ID_Tasks == id_tasks)
        ).unique().first()
        if not obj or not task_belongs_to_portal_user(session, obj):
            raise AppException("Task no encontrado.", "task_not_found", 404)
        return add_relationships(obj, ["job", "technician"]), 200


@tasks_bp.get("/job/<id_jobs>/tech/<id_tech>")
@require_permission("tasks:read")
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
        statement = scope_tasks_statement(statement)
        results = session.exec(statement).unique().all()
        if not results:
            return [], 200
        return [add_relationships(t, ["job", "technician"]) for t in results], 200


# --------------- RUTAS POST, PATCH AND DELETE----------#

@tasks_bp.post("/")
@require_permission("tasks:create")
@handle_exceptions()
@audit("Task created", entity_type="Tasks", id_from="response",
       job_id_from="response")
def create_tasks():
    data = request.get_json()
    create_tasks = TasksCreate.model_validate(data)
    obj = Tasks(
        **create_tasks.model_dump(exclude_unset=False, exclude_none=False))

    with get_session() as session:
        # Un rol de portal no cuelga tareas del tablero de un empleado de GQM.
        # `task_belongs_to_portal_user` mira job y subcontratista, no ID_Member.
        if llamante_es_portal() and obj.ID_Member:
            raise AppException(
                "Forbidden: no puedes asignar la tarea a un miembro de GQM.",
                "forbidden", 403)
        # Portal: un sub solo crea tareas dentro de lo suyo (IDOR de cobertura B7)
        if not task_belongs_to_portal_user(session, obj):
            raise AppException(
                "Forbidden: la tarea no pertenece a tus jobs.", "forbidden", 403)
        # P-07: la guarda de arriba valida el JOB, no el TÉCNICO DESTINO. Medido:
        # un sub creaba una tarea en SU job y se la asignaba a TEC60002, técnico
        # de OTRO sub → 201 y la fila quedaba escrita. Ambigüedad 2 ratificada:
        # el sub asigna, pero SOLO a los suyos (portal_owns_technician cubre
        # también al técnico, que solo puede asignarse a sí mismo; el staff pasa).
        # Aquí 403 y no 404 porque el id lo aporta el propio llamante: no se le
        # revela nada que no supiera ya (mismo criterio que Job.py:832-833).
        if obj.ID_Technician and not portal_owns_technician(
                session, obj.ID_Technician):
            raise AppException(
                "Forbidden: no puedes asignar la tarea a un técnico ajeno.",
                "forbidden", 403)
        # T-09: la tarea automática de certificado (sin job, con subcontratista)
        # se dedupe SOLO en localStorage, que es por navegador y dispositivo:
        # dos admins, dos equipos o un incógnito creaban duplicados, y el
        # .catch(() => null) del panel se tragaba los fallos. Aquí se hace
        # idempotente en servidor, que es donde el dedupe funciona para todos.
        if obj.ID_Subcontractor and not obj.ID_Jobs and obj.Name:
            ya = session.exec(
                select(Tasks).where(
                    Tasks.Name == obj.Name,
                    Tasks.ID_Subcontractor == obj.ID_Subcontractor,
                )).first()
            if ya is not None:
                logger.info("↩️  Task de certificado ya existía | task_id=%s",
                            ya.ID_Tasks)
                return ya.model_dump(), 200

        obj.ID_Tasks = generate_custom_id(session, Tasks, "ID_Tasks", "TSK")
        save_with_retry(session, obj)
        logger.info("✅ Task creada | task_id=%s", obj.ID_Tasks)
        return obj.model_dump(), 201


@tasks_bp.patch("/<task_id>")
@require_permission("tasks:update")
@handle_exceptions()
@audit("Task updated", entity_type="Tasks", id_param="task_id",
       job_id_from="response")
def update_tasks(task_id):
    data = request.get_json()
    with get_session() as session:
        obj = session.exec(select(Tasks).where(
            Tasks.ID_Tasks == task_id)).first()
        if not obj or not task_belongs_to_portal_user(session, obj):
            raise AppException("Task no encontrado.", "task_not_found", 404)

        update_data = TasksUpdate.model_validate(
            data).model_dump(exclude_unset=True)

        # Campos de VINCULO que un rol de portal no puede tocar. Se rechaza
        # ANTES de mutar el objeto, no despues: las guardas de abajo miran el
        # estado ya mutado y dos de ellas no ven este caso.
        #
        #  · ID_Jobs = None  es un BORRADO LOGICO. Medido: un tecnico anulaba
        #    el job de su tarea, devolvia 200, y la tarea desaparecia del portal
        #    de su subcontratista y del listado de todos — sin borrar la fila y
        #    sin pasar por DELETE, que R5 le prohibe. La guarda existente
        #    (`job_belongs_to_portal_user`) lo dejaba pasar porque devuelve True
        #    para un job_id vacio.
        #  · ID_Subcontractor  reasigna la PROPIEDAD de la tarea a otro
        #    contratista. Medido: A podia inyectar filas en el ambito de B.
        #  · ID_Member  cuelga la tarea del tablero de un empleado de GQM.
        if llamante_es_portal():
            if "ID_Jobs" in update_data and not update_data["ID_Jobs"]:
                raise AppException(
                    "Forbidden: no puedes desvincular la tarea de su job.",
                    "forbidden", 403)
            for campo in ("ID_Subcontractor", "ID_Member"):
                if campo in update_data and update_data[campo] != getattr(obj, campo):
                    raise AppException(
                        f"Forbidden: no puedes modificar {campo}.",
                        "forbidden", 403)

        for key, value in update_data.items():
            setattr(obj, key, value)
        # Re-chequeo POST-update: sin esto un rol de portal podía REASIGNAR
        # ID_Jobs/ID_Technician/ID_Subcontractor y mover su tarea a un job
        # ajeno (el guard de arriba solo mira el estado previo).
        if not task_belongs_to_portal_user(session, obj):
            raise AppException(
                "Forbidden: no puedes reasignar la tarea fuera de tus jobs.",
                "forbidden", 403)
        # T-26: para un TÉCNICO, task_belongs_to_portal_user solo compara
        # ID_Technician, que no cambia al reasignar ID_Jobs — así que la guarda
        # de arriba lo dejaba pasar y podía mover su tarea a un job ajeno.
        # (El sub sí quedaba cubierto porque su pertenencia es por job.)
        if "ID_Jobs" in update_data and not job_belongs_to_portal_user(
                session, obj.ID_Jobs):
            raise AppException(
                "Forbidden: no puedes reasignar la tarea fuera de tus jobs.",
                "forbidden", 403)
        # P-07 por la puerta del PATCH: las tres guardas anteriores miran el JOB,
        # y para un sub el job SIGUE SIENDO SUYO al reasignar el técnico — así
        # que podía pasar su tarea a un técnico de otro sub sin tocar el job.
        # Misma decisión que en el POST: solo a los suyos. Para el técnico el
        # caso ya lo cortaba el re-chequeo post-mutación (ID_Technician == él),
        # pero se deja explícito para que no dependa de ese orden.
        if update_data.get("ID_Technician") and not portal_owns_technician(
                session, obj.ID_Technician):
            raise AppException(
                "Forbidden: no puedes asignar la tarea a un técnico ajeno.",
                "forbidden", 403)
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
        if not obj or not task_belongs_to_portal_user(session, obj):
            raise AppException("Task no encontrado.", "task_not_found", 404)

        delete_with_retry(session, obj)
        logger.info("🗑️ Task eliminado | task_id=%s", task_id)
        return jsonify({"message": f"Task {task_id} eliminada correctamente"}), 200
