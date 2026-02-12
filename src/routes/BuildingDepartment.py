# ============ Lógica de rutas =================

from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.BldgDeptModel import BuildingDept, BuildingDeptCreate, BuildingDeptUpdate
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry


# Blueprint de Building Department:
bldg_dept_bp = Blueprint(
    "bldg_dept_blueprint", __name__, url_prefix="/bldg_dept")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los Building Departments
@bldg_dept_bp.get("/")
@paginate()
def list_bldg_dept():
    try:
        with get_session() as session:
            # Trae todas los Building Departments con info anidada
            statement = (
                select(BuildingDept)
                .options(
                    joinedload(BuildingDept.jobs),
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            bldg_dept_data = [
                add_relationships(bldg_dept, ["jobs"])
                for bldg_dept in results
            ]

            return bldg_dept_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(
            f"Error de base de datos al listar los Building Departments: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(
            f"Error inesperado al listar los Building Departments: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un Building Department por ID
@bldg_dept_bp.get("/<bldg_dept_id>")
def get_bldg_dept(bldg_dept_id):
    try:
        with get_session() as session:
            statement = (
                select(BuildingDept)
                .options(
                    joinedload(BuildingDept.jobs)
                )
                .where(BuildingDept.ID_BldgDept == bldg_dept_id)
            )

            results = session.exec(statement).unique().first()

            if not results:
                return jsonify({"error": "Building Department not found"}), 404

            bldg_dept_data = add_relationships(
                results, ["jobs"])

            return jsonify(bldg_dept_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar Building Department: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(
            f"Error inesperado al listar los Building Departments: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500
