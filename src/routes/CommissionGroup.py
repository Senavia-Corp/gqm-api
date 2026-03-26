# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.ComGroupModel import CommissionGroup, CommissionGrCreate, CommissionGrUpdate
from ..models.ComDetailModel import CommissionDetail
from ..models.JobModel import Job
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger

# Blueprint de CommissionGroup:
commission_group_bp = Blueprint(
    "commission_group_blueprint", __name__, url_prefix="/commission_group")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos las commission group
@commission_group_bp.get("/")
@handle_exceptions()
@paginate()
def list_comgr():

    with get_session() as session:

        job_load = joinedload(CommissionDetail.job).load_only(
            Job.ID_Jobs,
            Job.Job_type,
            Job.Gqm_premium_in_money,
            Job.Gqm_target_return,
            Job.ID_Client,
        )
        statement = (
            select(CommissionGroup)
            .options(
                joinedload(CommissionGroup.comdetails).options(job_load)
            )
        )
        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        comgr_data = []

        for comgr in results:
            data = add_relationships(comgr, ["comdetails.job"])

            for detail in data.get("comdetails", []):
                job = detail.get("job")
                if job:
                    detail["job"] = {
                        "ID_Jobs": job.get("ID_Jobs"),
                        "Job_type": job.get("Job_type"),
                        "Gqm_premium_in_money": job.get("Gqm_premium_in_money"),
                        "Gqm_target_return": job.get("Gqm_target_return"),
                        "ID_Client": job.get("ID_Client"),
                    }

            comgr_data.append(data)

        return comgr_data, 200


# Ruta para conseguir una commission group por ID_ComGroup
@commission_group_bp.get("/<id_comgr>")
@handle_exceptions()
def get_comgr_by_id(id_comgr):

    with get_session() as session:
        job_load = joinedload(CommissionDetail.job).load_only(
            Job.ID_Jobs,
            Job.Job_type,
            Job.Gqm_premium_in_money,
            Job.Gqm_target_return,
            Job.ID_Client,
        )

        statement = (
            select(CommissionGroup)
            .options(
                joinedload(CommissionGroup.comdetails).options(job_load)
            )
            .where(CommissionGroup.ID_ComGroup == id_comgr)
        )

        obj = session.exec(statement).unique().first()

        if not obj:
            raise AppException(
                "CommissionGroup no encontrado.",
                "comgr_not_found",
                404
            )

        comgr_data = add_relationships(obj, ["comdetails.job"])

        # 🔥 Recortar job (CLAVE)
        for detail in comgr_data.get("comdetails", []):
            job = detail.get("job")
            if job:
                detail["job"] = {
                    "ID_Jobs": job.get("ID_Jobs"),
                    "Job_type": job.get("Job_type"),
                    "Gqm_premium_in_money": job.get("Gqm_premium_in_money"),
                    "Gqm_target_return": job.get("Gqm_target_return"),
                    "ID_Client": job.get("ID_Client"),
                }

        return jsonify(comgr_data), 200


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear una commission group
@commission_group_bp.post("/")
@handle_exceptions()
def create_comgr():

    data = request.get_json()
    create_comgr = CommissionGrCreate.model_validate(data)
    obj = CommissionGroup.model_validate(create_comgr)

    with get_session() as session:

        # ----------- 🔵 CREAR EN DB
        new_id = generate_custom_id(
            session, CommissionGroup, "ID_ComGroup", "CGR")
        obj.ID_ComGroup = new_id

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        logger.info(
            "✅ CommissionGroup creado | commission_gr_id=%s",
            obj.ID_ComGroup
        )

        return obj.model_dump(), 201


# Ruta para actualizar una commission group
@commission_group_bp.patch("/<id_comgr>")
@handle_exceptions()
def update_comgr(id_comgr):

    data = request.get_json()

    with get_session() as session:
        obj = session.get(CommissionGroup, id_comgr)
        if not obj:
            raise AppException("CommissionGroup no encontrado.",
                               "comgr_not_found", 404)

        update_comgr = CommissionGrUpdate.model_validate(data)
        update_data_dict = update_comgr.model_dump(exclude_unset=True)

        # ----------- 🔄 ACTUALIZAR EN DB
        for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
            setattr(obj, key, value)

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        logger.info(
            "🔄 CommissionGroup actualizado | commission_gr_id=%s",
            obj.ID_ComGroup
        )

        return obj.model_dump(), 200


# Ruta para eliminar una commission group
@commission_group_bp.delete("/<id_comgr>")
@handle_exceptions()
def delete_comgr(id_comgr):

    with get_session() as session:
        obj = session.get(CommissionGroup, id_comgr)
        if not obj:
            raise AppException("CommissionGroup no encontrado.",
                               "comgr_not_found", 404)

        # ----------- 🔴 BORRAR EN DB
        delete_with_retry(session, obj)

        logger.info(
            "🗑️ CommissionGroup eliminado | commission_gr_id=%s",
            id_comgr
        )

        return jsonify({
            "message": f"CommissionGroup {id_comgr} eliminado correctamente"
        }), 200
