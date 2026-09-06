# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select, or_
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
from ..models.JobModel import Job
from ..models.ClientModel import Client
from ..utils.middleware.auth.routes_protection import (
    portal_scope,
    scope_jobs_statement,
    job_belongs_to_portal_user,
    portal_owns_subcontractor,
)


# Blueprint de TLActivity:
tlactivity_bp = Blueprint("tlactivity_blueprint",
                          __name__, url_prefix="/tlactivity")


# ── P-04 · alcance de LECTURA del timeline para roles de portal ──────────────
# main.py:257-269 movio las escrituras de este blueprint a `admin:sync` —eso
# cerro la mitad grave de H2, que un rol de portal FABRICARA auditoria— y dejo
# a proposito las GET por relacion en `tasks:read`, que es lo que consume el
# timeline del panel. Lo medido: con ese permiso los cinco sujetos de portal
# leian la actividad de CUALQUIER job, sub, cliente o gestora. Esta es la otra
# mitad, la lectura.
#
# El criterio es uno solo y se deriva de `scope_jobs_statement`, que ya sabe
# que jobs son del llamante: una fila de auditoria es alcanzable si cuelga de
# un job suyo. El staff (full_admin / gqm_member) sale por el `rol is None` de
# `portal_scope()` y no cambia de comportamiento en ninguna de las cinco rutas.


def _mis_jobs():
    """Subconsulta con los ID de los jobs que alcanza el llamante."""
    return scope_jobs_statement(select(Job.ID_Jobs))


def _tengo_job_con(session, condicion) -> bool:
    """¿Alcanza el llamante algun job que cumpla `condicion`? (staff: si).

    Un cliente y una gestora no tienen vinculo propio con el portal: su
    pertenencia solo se puede derivar de los jobs en los que trabaja.
    """
    if portal_scope()[0] is None:
        return True
    return session.exec(
        scope_jobs_statement(select(Job.ID_Jobs).where(condicion))
    ).first() is not None


def _acotar_filas_a_mis_jobs(statement):
    """Filas de un job del llamante, mas las que no cuelgan de ningun job.

    Las filas sin `ID_Jobs` son eventos de nivel cliente/gestora (asi las crea
    `seed_portal_audit.py`, y 141 filas de produccion estan igual — H1/H8). Se
    conservan porque la ruta ya ha comprobado que ese cliente es de un job
    suyo; sin ellas el timeline de cliente saldria siempre vacio. Lo que se
    corta es lo que filtraba: filas del mismo cliente colgadas del job de OTRO
    sub, que ademas expanden ese job entero en la respuesta (F-05).
    """
    if portal_scope()[0] is None:
        return statement
    return statement.where(or_(
        TLActivity.ID_Jobs.is_(None),
        TLActivity.ID_Jobs.in_(_mis_jobs()),
    ))


def _fila_alcanzable(session, obj) -> bool:
    """¿Puede el llamante leer ESTA fila suelta? (staff: si).

    Cuidado con `job_belongs_to_portal_user`: devuelve True cuando el job es
    nulo, contrato pensado para el staff. Como hay filas sin `ID_Jobs`, aqui se
    exige el job ANTES de preguntar, y una fila suelta solo se entrega a su
    propio sujeto.
    """
    rol, uid = portal_scope()
    if rol is None:
        return True
    if obj.ID_Jobs:
        return job_belongs_to_portal_user(session, obj.ID_Jobs)
    if rol == "subcontractor":
        return obj.ID_Subcontractor == uid
    return obj.ID_Technician == uid


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

            # P-04: esta ruta no comprobaba nada. Modismo de Tasks.py:170 —
            # «no existe» y «no es tuyo» responden LO MISMO (404), para que no
            # se pueda enumerar el log de auditoria fila a fila.
            if not obj or not _fila_alcanzable(session, obj):
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

            # P-04: el timeline de un job ajeno lo leian los cinco sujetos de
            # portal. 404 y no 403: un 403 confirmaria que el job existe y
            # dejaria la ruta enumerable (convencion de Job.py:506-507).
            if not job_belongs_to_portal_user(session, id_job):
                return jsonify({"error": "TLActivity not found"}), 404

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


# GET /tlactivity/parent-mgmt-co/<id_parent_mgmt_co>
@tlactivity_bp.get("/parent-mgmt-co/<id_parent_mgmt_co>")
@paginate()
def get_tlactivities_by_parent_mgmt_co(id_parent_mgmt_co):
    try:
        with get_session() as session:

            # P-04: una gestora solo es alcanzable a traves de los jobs del
            # llamante. `Job` no tiene ID_Community_Tracking: cuelga del
            # Client, de ahi el IN. La gestora ajena responde 404.
            if not _tengo_job_con(session, Job.ID_Client.in_(
                    select(Client.ID_Client).where(
                        Client.ID_Community_Tracking == id_parent_mgmt_co))):
                return jsonify({"error": "TLActivity not found"}), 404

            statement = (
                select(TLActivity)
                .options(
                    joinedload(TLActivity.member),
                    joinedload(TLActivity.job),
                )
                .where(TLActivity.ID_Community_Tracking == id_parent_mgmt_co)
                .order_by(TLActivity.Action_datetime.desc())
            )

            # Aunque la gestora sea suya, sus filas pueden colgar del job de
            # otro sub — y esta ruta expande `job` entero (F-05).
            statement = _acotar_filas_a_mis_jobs(statement)

            results = session.exec(statement).unique().all()

            if not results:
                return [], 200

            tla_data = [
                add_relationships(tla, ["member", "job"])
                for tla in results
            ]

            return tla_data, 200

    except SQLAlchemyError as db_error:
        print(f"Error de base de datos al listar tlactivities del parent_mgmt_co {id_parent_mgmt_co}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar tlactivities del parent_mgmt_co {id_parent_mgmt_co}: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500
# ─────────────────────────────────────────────────────────────────────────────


# GET /tlactivity/client/<id_client>
@tlactivity_bp.get("/client/<id_client>")
@paginate()
def get_tlactivities_by_client(id_client):
    try:
        with get_session() as session:

            # P-04: un rol de portal solo ve la actividad de los clientes de
            # SUS jobs; el cliente ajeno responde 404 y no 403 (misma razon:
            # no confirmar existencia — Job.py:506-507).
            if not _tengo_job_con(session, Job.ID_Client == id_client):
                return jsonify({"error": "TLActivity not found"}), 404

            statement = (
                select(TLActivity)
                .options(
                    joinedload(TLActivity.member),
                    joinedload(TLActivity.job),
                )
                .where(TLActivity.ID_Client == id_client)
                .order_by(TLActivity.Action_datetime.desc())
            )

            # Aunque el cliente sea suyo, sus filas pueden colgar del job de
            # otro sub — y esta ruta expande `job` entero (F-05).
            statement = _acotar_filas_a_mis_jobs(statement)

            results = session.exec(statement).unique().all()

            if not results:
                return [], 200

            tla_data = [
                add_relationships(tla, ["member", "job"])
                for tla in results
            ]

            return tla_data, 200

    except SQLAlchemyError as db_error:
        print(f"Error de base de datos al listar tlactivities del client {id_client}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar tlactivities del client {id_client}: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500
# ─────────────────────────────────────────────────────────────────────────────


# GET /tlactivity/subcontractor/<id_subcontractor>
@tlactivity_bp.get("/subcontractor/<id_subcontractor>")
@paginate()
def get_tlactivities_by_subcontractor(id_subcontractor):
    try:
        with get_session() as session:

            # P-04: un sub no ve NADA de otro sub (ambiguedad 5 ratificada);
            # lo ajeno responde 404, no 403. Un tecnico no es dueno de ninguna
            # ficha de sub, pero el panel le pinta el timeline de su cuadrilla:
            # se le deja pasar acotado a los jobs que ya alcanza por
            # /tlactivity/job/<id>, y ahi no valen las filas sin job porque
            # serian de un sub ajeno.
            rol_portal, _ = portal_scope()
            if rol_portal == "subcontractor" and not portal_owns_subcontractor(
                    id_subcontractor):
                return jsonify({"error": "TLActivity not found"}), 404

            statement = (
                select(TLActivity)
                .options(
                    joinedload(TLActivity.member),
                    joinedload(TLActivity.job),
                )
                .where(TLActivity.ID_Subcontractor == id_subcontractor)
                .order_by(TLActivity.Action_datetime.desc())
            )

            if rol_portal == "technician":
                statement = statement.where(
                    TLActivity.ID_Jobs.in_(_mis_jobs()))

            results = session.exec(statement).unique().all()

            if not results:
                return [], 200

            tla_data = [
                add_relationships(tla, ["member", "job"])
                for tla in results
            ]

            return tla_data, 200

    except SQLAlchemyError as db_error:
        print(f"Error de base de datos al listar tlactivities del subcontractor {id_subcontractor}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar tlactivities del subcontractor {id_subcontractor}: {e}")
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