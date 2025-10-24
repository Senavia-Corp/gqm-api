# ======================================== Código para la Base de Datos en Postgresql =================================
from ..models.ClientModel import podio_list_clients
from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.ClientModel import Client, ClientCreate, ClientUpdate
from ..utils.id_generator import generate_custom_id
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from pydantic import ValidationError

# Blueprint de Client:
client_bp = Blueprint("client_blueprint", __name__, url_prefix="/clients")

# -------------------RUTAS CRUD-------------------#

# Ruta para conseguir la lista de todos los clientes


@client_bp.get("/")
def list_suppliers():
    try:
        with get_session() as session:
            results = session.exec(select(Client)).all()
            return jsonify([obj.model_dump() for obj in results]), 200

    except SQLAlchemyError as db_error:  # Para un fallo de db
        print(f"Error de base de datos al listar proveedores: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:  # Para un fallo general inesperado
        print(f"Error inesperado al listar proveedores: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500


# Ruta para conseguir un cliente por ID
@client_bp.get("/<id_client>")
def get_client(id_client):
    try:
        with get_session() as session:
            obj = session.get(Client, id_client)
            if not obj:
                return jsonify({"error": "Client not found"}), 404
            return jsonify(obj.model_dump()), 200

    except SQLAlchemyError as db_error:
        print(
            f"Error de base de datos al buscar proveedor {id_client}: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al consultar la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        print(f"Error inesperado al listar proveedores: {e}")
        return jsonify({
            "detail": "Error interno inesperado del servidor.",
            "code": "internal_error"
        }), 500

# Ruta para crear un cliente


@client_bp.post("/")
def create_client():
    try:
        data = request.get_json()
        create_client = ClientCreate.model_validate(data)
        obj = Client.model_validate(create_client)

    except ValidationError as e:
        if 'JSON' in str(e):
            return jsonify({"detail": "La solicitud debe contener un JSON válido."}), 400
        print(f"Error inesperado en preparación de datos: {e}")
        return jsonify({"detail": "Error inesperado del servidor."}), 500

    try:
        with get_session() as session:
            new_id = generate_custom_id(
                session, Client, "ID_Client", "CLI")
            obj.ID_Client = new_id

            session.add(obj)
            session.commit()
            session.refresh(obj)
            return jsonify(obj.model_dump()), 201

    except IntegrityError as e:  # Cuando violas una restricción UNIQUE o NOT NULL
        session.rollback()  # Deshace los cambios realizados
        error_message = str(e)
        if "UNIQUE constraint failed" in error_message:
            detail = "Ya existe un proveedor con este valor único."
        else:
            detail = "Error de integridad de datos (ej. dato requerido faltante o clave foránea inválida)."
        print(f"Error de integridad: {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:  # Problemas de infraestructura de DB
        session.rollback()
        print(f"Error de base de datos al crear proveedor: {db_error}")
        return jsonify({
            "detail": "Error interno del servidor al interactuar con la base de datos.",
            "code": "db_error"
        }), 500

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass

        print(f"Error inesperado durante la creación de proveedor: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500

# Ruta para actualizar un cliente


@client_bp.patch("/<id_client>")
def update_client(id_client):
    session = None  # Para que funcione except
    try:
        data = request.get_json()
        with get_session() as session:
            obj = session.get(Client, id_client)
            if not obj:
                return jsonify({"error": "Client not found"}), 404

            update_client = ClientUpdate.model_validate(data)
            update_data_dict = update_client.model_dump(
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
            "detail": "Error de validación: Datos de proveedor inválidos para la actualización.",
            "errors": e.errors()
        }), 400

    except IntegrityError as e:
        if session:
            session.rollback()
        detail = "Error de integridad: Ya existe un proveedor con estos valores únicos o faltan datos requeridos."
        print(f"Error de integridad (PATCH): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al actualizar proveedor: {db_error}")
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
        print(f"Error inesperado al actualizar proveedor: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500

# Ruta para eliminar un cliente


@client_bp.delete("/<id_client>")
def delete_client(id_client):
    session = None
    try:
        with get_session() as session:
            obj = session.get(Client, id_client)
            if not obj:
                return jsonify({"error": "Client not found"}), 404
            session.delete(obj)
            session.commit()
            return jsonify({"message": f"Deleted Client {id_client}"}), 200

    # Exceptions de integridad, infraestructura e inesperado del servidor
    except IntegrityError as e:  # En caso de borrar un proveedor que tiene productos asociados con Foreign Key
        if session:
            session.rollback()
        detail = "Error de integridad: No se puede eliminar el proveedor porque tiene registros relacionados."
        print(f"Error de integridad (DELETE): {e}")
        return jsonify({"detail": detail}), 409

    except SQLAlchemyError as db_error:
        if session:
            session.rollback()
        print(f"Error de base de datos al eliminar proveedor: {db_error}")
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
        print(f"Error inesperado al eliminar proveedor: {e}")
        return jsonify({
            "detail": "Ocurrió un error inesperado y no controlado en el servidor.",
            "code": "internal_error"
        }), 500


# =============================================== Código de para la conexión y manejo de Podio =================================


@client_bp.get("/podio/items")
def clients_from_podio():
    limit = int(request.args.get("limit", 200))
    offset = int(request.args.get("offset", 0))
    fetch_all = str(request.args.get("all", "false")
                    ).lower() in ("1", "true", "yes")
    view_id = request.args.get("view_id")
    fmt = (request.args.get("format") or "normalized").lower()
    category_mode = (request.args.get("category_mode") or "both").lower()

    data = podio_list_clients(
        limit=limit, offset=offset, fetch_all=fetch_all, view_id=view_id,
        fmt=fmt, category_mode=category_mode
    )
    return jsonify(data), 200
