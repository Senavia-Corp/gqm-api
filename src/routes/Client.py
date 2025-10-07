#======================================== Código para la Base de Datos en Postgresql =================================
from flask import Blueprint, jsonify, request
from sqlalchemy import select
from ..database.db import db, get_connection
from ..models.ClientModel import ClientORM

client_bp = Blueprint("client_blueprint", __name__, url_prefix="/clients")

@client_bp.get("/")
def list_clients():
    """
    GET /clients
    Devuelve todos los clientes (simple). 
    Puedes agregar paginación luego con ?limit=&offset=
    """
    s = get_connection()
    rows = s.execute(select(ClientORM)).scalars().all()
    return jsonify([r.to_dict() for r in rows]), 200


@client_bp.get("/<id_client>")
def get_client(id_client):
    """
    GET /clients/<id_client>
    Devuelve un cliente por ID o 404 si no existe.
    """
    s = get_connection()
    obj = s.get(ClientORM, id_client)
    if not obj:
        return jsonify({"message": "Client not found"}), 404
    return jsonify(obj.to_dict()), 200


@client_bp.post("/")
def create_client():
    """
    POST /clients
    Body JSON mínimo esperado:
    {
      "id_client": "C-001",
      "client_community": "Client or Community name",
      "parent_mgmt_company": "Parent Mgmt Company name"
    }
    """
    data = request.get_json(force=True, silent=False)
    missing = [k for k in ("id_client",) if k not in data or data[k] in (None, "")]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    s = get_connection()
    # Validar duplicado (PK)
    if s.get(ClientORM, data["id_client"]):
        return jsonify({"error": "Client with that id_client already exists"}), 409

    obj = ClientORM(
        id_client=data["id_client"],
        client_community=data.get("client_community"),
        parent_mgmt_company=data.get("parent_mgmt_company"),
    )
    s.add(obj)
    s.commit()  # importante: persiste
    return jsonify(obj.to_dict()), 201


@client_bp.put("/<id_client>")
def update_client(id_client):
    """
    PUT /clients/<id_client>
    Actualiza campos existentes. No cambia el ID.
    Body JSON puede incluir cualquiera de:
      client_community, parent_mgmt_company
    """
    data = request.get_json(force=True, silent=False)
    s = get_connection()
    obj = s.get(ClientORM, id_client)
    if not obj:
        return jsonify({"message": "Client not found"}), 404

    # Aplica cambios si vienen en el body
    if "client_community" in data:
        obj.client_community = data["client_community"]
    if "parent_mgmt_company" in data:
        obj.parent_mgmt_company = data["parent_mgmt_company"]

    s.commit()
    return jsonify(obj.to_dict()), 200


@client_bp.delete("/<id_client>")
def delete_client(id_client):
    """
    DELETE /clients/<id_client>
    Elimina por ID si existe.
    """
    s = get_connection()
    obj = s.get(ClientORM, id_client)
    if not obj:
        return jsonify({"message": "Client not found"}), 404
    s.delete(obj)
    s.commit()
    return jsonify({"message": f"Client deleted: {id_client}"}), 200


#=============================================== Código de para la conexión y manejo de Podio =================================
from ..models.ClientModel import ClientORM, podio_list_clients

from ..models.ClientModel import ClientORM, podio_list_clients

@client_bp.get("/podio/items")
def clients_from_podio():
    limit = int(request.args.get("limit", 200))
    offset = int(request.args.get("offset", 0))
    fetch_all = str(request.args.get("all", "false")).lower() in ("1", "true", "yes")
    view_id = request.args.get("view_id")
    fmt = (request.args.get("format") or "normalized").lower()
    category_mode = (request.args.get("category_mode") or "both").lower()

    data = podio_list_clients(
        limit=limit, offset=offset, fetch_all=fetch_all, view_id=view_id,
        fmt=fmt, category_mode=category_mode
    )
    return jsonify(data), 200
