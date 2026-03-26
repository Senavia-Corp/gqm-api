# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.ComDetailModel import CommissionDetail, CommissionDeCreate, CommissionDeUpdate
from ..models.JobModel import Job
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger
from ..utils.commission_calculator import calculate_sell_mgmt, recalculate_all

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
            Job.Gqm_premium_in_money,
            Job.Gqm_target_return,
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
                    "Gqm_premium_in_money": job.get("Gqm_premium_in_money"),
                    "Gqm_target_return": job.get("Gqm_target_return"),
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
            Job.Gqm_premium_in_money,
            Job.Gqm_target_return,
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
                "Gqm_premium_in_money": job.get("Gqm_premium_in_money"),
                "Gqm_target_return": job.get("Gqm_target_return"),
                "ID_Client": job.get("ID_Client"),
            }

        return jsonify(comdetail_data), 200


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un commission detail
@commission_detail_bp.post("/")
@handle_exceptions()
def create_comdetail():

    data = request.get_json()
    create_obj = CommissionDeCreate.model_validate(data)
    obj = CommissionDetail.model_validate(create_obj)

    with get_session() as session:

        # ----------- 🔍 OBTENER JOB PARA EL CÁLCULO
        job = session.get(Job, obj.ID_Jobs)
        if not job:
            raise AppException("Job no encontrado.", "job_not_found", 404)

        # ----------- 🧮 CALCULAR SELL_MGMT
        obj.Sell_Mgmt = calculate_sell_mgmt(
            obj.Factor or 0,
            job.Gqm_premium_in_money or 0)

        # ----------- 🔵 CREAR EN DB
        new_id = generate_custom_id(
            session, CommissionDetail, "ID_ComDetail", "CDT"
        )
        obj.ID_ComDetail = new_id

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        # ----------- 🔄 REFRESH para rehidratar atributos post-commit
        session.refresh(obj)
        print("ID_ComGroup después de refresh:", obj.ID_ComGroup)

        # ----------- 🔁 RECALCULAR CADENA HACIA ARRIBA
        recalculate_all(obj, session)

        # ----------- 💾 COMMIT FINAL para guardar totales
        session.commit()

        logger.info(
            "✅ CommissionDetail creado | commission_detail_id=%s",
            obj.ID_ComDetail
        )

        return obj.model_dump(), 201


# Ruta para actualizar un commission detail
@commission_detail_bp.patch("/<id_comdetail>")
@handle_exceptions()
def update_comdetail(id_comdetail):

    data = request.get_json()

    with get_session() as session:
        obj = session.get(CommissionDetail, id_comdetail)

        if not obj:
            raise AppException(
                "CommissionDetail no encontrado.",
                "comdetail_not_found",
                404
            )

        update_obj = CommissionDeUpdate.model_validate(data)
        update_data_dict = update_obj.model_dump(exclude_unset=True)

        # ----------- 🔄 ACTUALIZAR EN DB
        for key, value in update_data_dict.items():
            setattr(obj, key, value)

        # ----------- 🧮 RECALCULAR SELL_MGMT si cambió Factor o ID_Jobs
        if "Factor" in update_data_dict or "ID_Jobs" in update_data_dict:
            job = session.get(Job, obj.ID_Jobs)
            if not job:
                raise AppException("Job no encontrado.", "job_not_found", 404)
            obj.Sell_Mgmt = calculate_sell_mgmt(
                obj.Factor or 0,
                job.Gqm_premium_in_money or 0
            )

        # ----------- 💾 GUARDAR EN DB
        save_with_retry(session, obj)

        # ----------- 🔄 REFRESH para rehidratar atributos post-commit
        session.refresh(obj)
        print("ID_ComGroup después de refresh:", obj.ID_ComGroup)

        # ----------- 🔁 RECALCULAR CADENA HACIA ARRIBA
        recalculate_all(obj, session)

        # ----------- 💾 COMMIT FINAL para guardar totales
        session.commit()

        logger.info(
            "🔄 CommissionDetail actualizado | commission_detail_id=%s",
            obj.ID_ComDetail
        )

        return obj.model_dump(), 200


# Ruta para eliminar un commission detail
@commission_detail_bp.delete("/<id_comdetail>")
@handle_exceptions()
def delete_comdetail(id_comdetail):

    with get_session() as session:
        obj = session.get(CommissionDetail, id_comdetail)

        if not obj:
            raise AppException(
                "CommissionDetail no encontrado.",
                "comdetail_not_found",
                404
            )

        # ----------- 💾 GUARDAR REFERENCIAS ANTES DE BORRAR
        id_comgroup = obj.ID_ComGroup

        # ----------- 🔴 BORRAR EN DB
        delete_with_retry(session, obj)

        # ----------- 🔁 Restaurar referencia por si delete_with_retry la limpió
        obj.ID_ComGroup = id_comgroup

        # ----------- 🔁 RECALCULAR CADENA HACIA ARRIBA
        recalculate_all(obj, session)

        # ----------- 💾 COMMIT FINAL para guardar totales
        session.commit()

        logger.info(
            "🗑️ CommissionDetail eliminado | commission_detail_id=%s",
            id_comdetail
        )

        return jsonify({
            "message": f"CommissionDetail {id_comdetail} eliminado correctamente"
        }), 200
