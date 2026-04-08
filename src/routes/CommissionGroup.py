# ============ Lógica de rutas =================

from flask import Blueprint, jsonify
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.ComGroupModel import CommissionGroup
from ..models.ComDetailModel import CommissionDetail
from ..models.JobModel import Job
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.orm import joinedload
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException

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
