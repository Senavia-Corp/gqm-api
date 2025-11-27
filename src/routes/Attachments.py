# ======================================== Código para la Base de Datos en Postgresql =================================
from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.AttachmentsModel import Attachments, AttachmentsCreate, AttachmentsUpdate
from ..utils.id_generator import generate_custom_id
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import joinedload
from ..utils.relationships import add_relationships

# Blueprint de Attachments:
attachments_bp = Blueprint("attachments_blueprint",
                           __name__, url_prefix="/attachments")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los attachments
@attachments_bp.get("/")
def list_attachments():
    try:
        with get_session() as session:
            # Trae los Jobs con sus clientes en una sola consulta
            statement = (
                select(Attachments)
                .options(
                    joinedload(Attachments.job)
                )
            )
            results = session.exec(statement).unique().all()

            if not results:
                return jsonify("No se han encontrado archivos adjuntos en esta consulta."), 404

            attachments_data = [
                # se agrega la relacion FK
                add_relationships(attachments, ["job"])
                for attachments in results
            ]

            return attachments_data, 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(
            f"Error de base de datos al listar los archivos adjuntos: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Error inesperado al listar los archivos adjuntos: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un attachment por ID
@attachments_bp.get("/<id_attachment>")
def get_attachment_by_id(id_attachment):
    try:
        with get_session() as session:
            statement = (
                select(Attachments)
                .options(
                    joinedload(Attachments.job)
                )
                .where(Attachments.ID_Attachment == id_attachment)
            )
            obj = session.exec(statement).unique().first()

            if not obj:
                return jsonify({"error": "Attachment not found"}), 404

            attachment_data = add_relationships(
                obj, ["job"])

            return jsonify(attachment_data), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar archivo adjunto {id_attachment}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar archivos adjuntos: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# --------------- RUTAS POST, PATCH AND DELETE----------#
# Ruta para crear un attachment
@attachments_bp.post("/")
def create_attachment():
    try:
        data = request.get_json()
        create_attachment = AttachmentsCreate.model_validate(data)
        obj = Attachments.model_validate(create_attachment)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, Attachments, "ID_Attachment", "ATT")
            obj.ID_Attachment = new_id

            session.add(obj)
            session.commit()
            session.refresh(obj)
            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:  # Cuando violas una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un archivo adjunto con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Error de base de datos al crear archivo adjunto: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Error inesperado durante la creación del archivo adjunto: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para actualizar un attachment
@attachments_bp.patch("/<id_attachment>")
def update_attachment(id_attachment):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(Attachments, id_attachment)
            if not obj:
                return jsonify({"error": "Attachment not found"}), 404

            update_attachment = AttachmentsUpdate.model_validate(data)
            update_data_dict = update_attachment.model_dump(
                exclude_unset=True)  # Crea dict limpio

            for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
                setattr(obj, key, value)

            session.add(obj)
            session.commit()
            session.refresh(obj)
            return jsonify(obj.model_dump()), 200

    # Exceptions de errores de validacion, integridad, infraestructura o inesperado del servidor.
    except ValidationError as e:
        return jsonify({
            "detail": "Error de validación: Datos del archivo adjunto inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un archivo adjunto con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al actualizar archivo adjunto: {db_error}")
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
        print(f"Error inesperado al actualizar cliente: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# Ruta para eliminar un attachment
@attachments_bp.delete("/<id_attachment>")
def delete_attachment(id_attachment):
    session = None
    try:
        with get_session() as session:
            obj = session.get(Attachments, id_attachment)
            if not obj:
                return jsonify({"error": "Attachment not found"}), 404
            session.delete(obj)
            session.commit()
            return jsonify({"message": f"Deleted Attachment {id_attachment}"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:  # En caso de borrar un proveedor que tiene productos asociados con Foreign Key
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el archivo adjunto porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(
            f"Error de base de datos al eliminar archivo adjunto: {db_error}")
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
        print(f"Error inesperado al eliminar archivo adjunto: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500
