# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.ComDetailModel import CommissionDetail, CommissionDeUpdate
from ..models.JobModel import Job
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger
from ..utils.commission_calculator import recalculate_all

# Blueprint de CommissionDetail:
commission_detail_bp = Blueprint(
    "commission_detail_blueprint", __name__, url_prefix="/commission_detail")


# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los commission detail
@commission_detail_bp.get("/")
@handle_exceptions()
@paginate()  # decorador de paginación
def list_comdetail():

    with get_session() as session:

        job_load = joinedload(CommissionDetail.job).load_only(
            Job.ID_Jobs,
            Job.Job_type,
            Job.Gqm_final_prem_in_money,
            Job.Gqm_target_return,
            Job.Gqm_final_percentage,
            Job.ID_Client,
        )

        statement = select(CommissionDetail).options(job_load)

        results = session.exec(statement).unique().all()

        if not results:
            return [], 200

        comdetail_data = []

        for detail in results:
            data = add_relationships(detail, ["job"])

            job = data.get("job")
            if job:
                data["job"] = {
                    "ID_Jobs": job.get("ID_Jobs"),
                    "Job_type": job.get("Job_type"),
                    "Gqm_final_prem_in_money": job.get("Gqm_final_prem_in_money"),
                    "Gqm_target_return": job.get("Gqm_target_return"),
                    "Gqm_final_percentage": job.get("Gqm_final_percentage"),
                    "ID_Client": job.get("ID_Client"),
                }

            comdetail_data.append(data)

        return comdetail_data, 200


# Ruta para conseguir un commission detail por ID
@commission_detail_bp.get("/<id_comdetail>")
@handle_exceptions()
def get_comdetail_by_id(id_comdetail):

    with get_session() as session:

        job_load = joinedload(CommissionDetail.job).load_only(
            Job.ID_Jobs,
            Job.Job_type,
            Job.Gqm_final_prem_in_money,
            Job.Gqm_target_return,
            Job.Gqm_final_percentage,
            Job.ID_Client,
        )

        statement = (
            select(CommissionDetail)
            .options(job_load)
            .where(CommissionDetail.ID_ComDetail == id_comdetail)
        )

        obj = session.exec(statement).unique().first()

        if not obj:
            raise AppException(
                "CommissionDetail no encontrado.",
                "comdetail_not_found",
                404
            )

        comdetail_data = add_relationships(obj, ["job"])

        job = comdetail_data.get("job")
        if job:
            comdetail_data["job"] = {
                "ID_Jobs": job.get("ID_Jobs"),
                "Job_type": job.get("Job_type"),
                "Gqm_final_prem_in_money": job.get("Gqm_final_prem_in_money"),
                "Gqm_target_return": job.get("Gqm_target_return"),
                "Gqm_final_percentage": job.get("Gqm_final_percentage"),
                "ID_Client": job.get("ID_Client"),
            }

        return jsonify(comdetail_data), 200


# --------------- RUTA PATCH--------------- #

# Ruta para actualizar un commission detail
@commission_detail_bp.patch("/<id_comdetail>")
@handle_exceptions()
def update_comdetail(id_comdetail):
    data = request.get_json()

    with get_session() as session:
        # 1. Trae el detalle con su Grupo y Job cargados para tener los datos de cálculo
        statement = select(CommissionDetail).where(
            CommissionDetail.ID_ComDetail == id_comdetail
        ).options(
            joinedload(CommissionDetail.comgroup),
            joinedload(CommissionDetail.job)
        )
        obj = session.exec(statement).unique().first()

        if not obj:
            raise AppException(
                "CommissionDetail no encontrado.", "comdetail_not_found", 404)

        # 2. Validar el nuevo Type (Standard / Premium)
        update_obj = CommissionDeUpdate.model_validate(data)
        new_type = update_obj.Type

        if new_type:
            obj.Type = new_type

            # --- 🤖 AUTOMATIZACIÓN DEL FACTOR ---
            # Sacar el Rol del grupo y el dinero del Job
            rol = obj.comgroup.Rol
            # Usando el campo final que definimos
            money_base = obj.job.Gqm_final_prem_in_money or 0

            # Matriz de la foto:
            if new_type == "Standard":
                obj.Factor = 0.036 if rol == "Acc Rep Selling" else 0.018
            elif new_type == "Premium":
                obj.Factor = 0.054 if rol == "Acc Rep Selling" else 0.036

            # --- 🧮 CÁLCULO FINAL ---
            obj.Sell_Mgmt = money_base * obj.Factor

        # 3. Guardar cambios del detalle
        save_with_retry(session, obj)
        session.flush()  # Asegura que los cambios lleguen a la DB antes de recalcular totales

        # 4. Recalcular totales hacia arriba (Group -> Commission)
        recalculate_all(obj, session)

        session.commit()

        logger.info(f"✅ Detail actualizado a {new_type} | ID: {id_comdetail}")
        return obj.model_dump(), 200
