# ======================================== Código para la Base de Datos en Postgresql =================================
from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.EstimateCostModel import EstimateCost, EstimateCreate, EstimateUpdate
from ..utils.id_generator import generate_custom_id
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.relationships import add_relationships
from ..utils.pagination import paginate
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry

from ..podio.services.job_services import podio_jobs_router

from ..utils.mappers.to_podio.qid_mapper import map_job_to_podio_qid
from ..utils.mappers.to_podio.ptl_mapper import map_job_to_podio_ptl
from ..utils.mappers.to_podio.par_mapper import map_job_to_podio_par

# Blueprint de Estimate Cost:
estimate_bp = Blueprint("estimate_blueprint", __name__, url_prefix="/estimate")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los estimate costs
@estimate_bp.get("/")
@paginate()
def list_estimates():
    try:
        with get_session() as session:
            statement = (
                select(EstimateCost)
                .options(
                    joinedload(EstimateCost.job),
                    joinedload(EstimateCost.order),
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            estimate_data = [
                add_relationships(
                    estimate, ["job", "order"])
                for estimate in results
            ]

            return estimate_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(f"Database error while listing estimate costs: {db_error}")
        return jsonify({
            "detail": "Internal server error while querying the database.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Unexpected error while listing estimate costs: {e}")
        return jsonify({
            "detail": "Unexpected internal server error.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un estimate cost por ID
@estimate_bp.get("/<id_estimate>")
def get_estimates(id_estimate):
    try:
        with get_session() as session:
            statement = (
                select(EstimateCost)
                .options(
                    joinedload(EstimateCost.job),
                    joinedload(EstimateCost.order),
                )
                .where(EstimateCost.ID_EstimateCost == id_estimate)
            )

            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "Estimate Cost not found"}), 404

            estimate_data = add_relationships(
                obj, ["job", "order"])

            return jsonify(estimate_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Database error while fetching estimate cost {id_estimate}: {db_error}")
        return jsonify({
            "detail": "Internal server error while querying the database.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Unexpected error while listing estimate costs: {e}")
        return jsonify({
            "detail": "Unexpected internal server error.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear una order
@estimate_bp.post("/")
def create_estimate():
    try:
        data = request.get_json()
        create_estimate = EstimateCreate.model_validate(data)
        obj = EstimateCost(
            **create_estimate.model_dump(exclude_unset=False, exclude_none=False))

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "The request must contain valid JSON."}), 400
        print(f"Unexpected error in data preparation: {e}")
        return jsonify({"detail": "Unexpected server error."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, EstimateCost, "ID_EstimateCost", "EST")
            obj.ID_EstimateCost = new_id

            save_with_retry(session, obj)

            # Mapear a Podio

            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:  # Cuando violas una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "An estimate cost with this unique value already exists."
        else:
            detail = "Data integrity error (e.g., missing required data or invalid foreign key)."
        print(f"Data integrity error: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Database error while creating estimate cost: {db_error}")
        return jsonify({
            "detail": "Internal server error when interacting with the database.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Unexpected error during estimate cost creation: {e}")
        return jsonify({
            "detail": "An unexpected and uncontrolled error occurred on the server.",
            "code": "internal_error"
        }), 500
