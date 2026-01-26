from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.PaymentUnitModel import PaymentUnit, PaymentUCreate, PaymentUUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.pagination import paginate
from ..utils.relationships import add_relationships
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry


# Blueprint de Payment Unit
payment_unit_bp = Blueprint(
    "payment_unit_blueprint", __name__, url_prefix="/payment_unit")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los payment units
@payment_unit_bp.get("/")
@paginate()
def list_payment_units():
    try:
        with get_session() as session:

            statement = (
                select(PaymentUnit)
                .options(
                    joinedload(PaymentUnit.jobs),
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return [], 404

            paymentU_data = [
                add_relationships(
                    payment_u, ["jobs"])
                for payment_u in results
            ]

            return paymentU_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(f"Error de base de datos al listar payment units: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Error inesperado al listar payment units: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir payment unit por ID
@payment_unit_bp.get("/<id_payment_unit>")
def get_payment_unit(id_payment_unit):
    try:
        with get_session() as session:

            statement = (
                select(PaymentUnit)
                .options(
                    joinedload(PaymentUnit.jobs),
                )
                .where(PaymentUnit.ID_PaymentU == id_payment_unit)
            )

            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "Payment Unit not found"}), 404

            paymentU_data = add_relationships(obj, ["jobs"])

            return jsonify(paymentU_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar payment unit {id_payment_unit}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar payment units: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un payment unit
@payment_unit_bp.post("/")
def create_paymentU():
    try:
        data = request.get_json()
        create_paymentU = PaymentUCreate.model_validate(data)
        obj = PaymentUnit.model_validate(create_paymentU)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, PaymentUnit, "ID_PaymentU", "PayU")
            obj.ID_PaymentU = new_id

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:  # Cuando violas una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un payment unit con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Error de base de datos al crear payment unit: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Error inesperado durante la creación de payment unit: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar un payment unit
@payment_unit_bp.patch("/<id_payment_unit>")
def update_paymentU(id_payment_unit):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(PaymentUnit, id_payment_unit)
            if not obj:
                return jsonify({"error": "Payment Unit not found"}), 404

            update_paymentU = PaymentUUpdate.model_validate(data)
            update_data_dict = update_paymentU.model_dump(
                exclude_unset=True)  # Crea dict limpio

            for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
                setattr(obj, key, value)

            save_with_retry(session, obj)

            return jsonify(obj.model_dump()), 200

    # Exceptions de errores de validacion, integridad, infraestructura o inesperado del servidor.
    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos de payment unit inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un payment unit con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al actualizar payment unit: {db_error}")
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
        print(f"Error inesperado al actualizar payment unit: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para eliminar un subcontratista
@payment_unit_bp.delete("/<id_payment_unit>")
def delete_subcontractor(id_payment_unit):
    session = None
    try:
        with get_session() as session:
            obj = session.get(PaymentUnit, id_payment_unit)
            if not obj:
                return jsonify({"error": "Payment Unit not found"}), 404

            delete_with_retry(session, obj)

            return jsonify({"message": f"Deleted Payment Unit {id_payment_unit}"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:  # En caso de borrar un payment unit que tiene productos asociados con Foreign Key
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el payment unit porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar payment unit: {db_error}")
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
        print(f"Error inesperado al eliminar payment unit: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
