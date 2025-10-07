from flask import Blueprint, jsonify, request
from sqlalchemy import select
from ..database.db import get_connection
from ..models.SubcontractorModel import (
    SubcontractorORM,
    podio_list_subcontractors,
)

subcontractor_bp = Blueprint("subcontractor_blueprint", __name__, url_prefix="/subcontractors")

# ---------- CRUD LOCAL (Postgres) ----------

@subcontractor_bp.get("/")
def list_subcontractors():
    s = get_connection()
    rows = s.execute(select(SubcontractorORM)).scalars().all()
    return jsonify([r.to_dict() for r in rows]), 200


@subcontractor_bp.get("/<id_subcontractor>")
def get_subcontractor(id_subcontractor):
    s = get_connection()
    obj = s.get(SubcontractorORM, id_subcontractor)
    if not obj:
        return jsonify({"message": "Subcontractor not found"}), 404
    return jsonify(obj.to_dict()), 200


@subcontractor_bp.post("/")
def create_subcontractor():
    data = request.get_json(force=True, silent=False)

    missing = [k for k in ("id_subcontractor",) if k not in data or data[k] in (None, "")]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    s = get_connection()
    if s.get(SubcontractorORM, data["id_subcontractor"]):
        return jsonify({"error": "Subcontractor with that id_subcontractor already exists"}), 409

    obj = SubcontractorORM(
        id_subcontractor=data["id_subcontractor"],
        organization=data.get("organization"),
        name=data.get("name"),
        email=data.get("email"),
        phone=data.get("phone"),
        organization_web_site=data.get("organization_web_site"),
        address=data.get("address"),
        state=data.get("state"),
        score=data.get("score"),
        gqm_compliancegqm=data.get("gqm_compliancegqm"),
        best_service_training=data.get("best_service_training"),
        id_rol=data.get("id_rol"),
    )
    s.add(obj)
    s.commit()
    return jsonify(obj.to_dict()), 201


@subcontractor_bp.put("/<id_subcontractor>")
def update_subcontractor(id_subcontractor):
    data = request.get_json(force=True, silent=False)
    s = get_connection()
    obj = s.get(SubcontractorORM, id_subcontractor)
    if not obj:
        return jsonify({"message": "Subcontractor not found"}), 404

    # Aplica solo campos presentes
    for key in (
        "organization","name","email","phone","organization_web_site","address",
        "state","score","gqm_compliancegqm","best_service_training","id_rol"
    ):
        if key in data:
            setattr(obj, key, data[key])

    s.commit()
    return jsonify(obj.to_dict()), 200


@subcontractor_bp.delete("/<id_subcontractor>")
def delete_subcontractor(id_subcontractor):
    s = get_connection()
    obj = s.get(SubcontractorORM, id_subcontractor)
    if not obj:
        return jsonify({"message": "Subcontractor not found"}), 404
    s.delete(obj)
    s.commit()
    return jsonify({"message": f"Subcontractor deleted: {id_subcontractor}"}), 200


# ---------- PODIO (Subcontractors App) ----------

@subcontractor_bp.get("/podio/items")
def subcontractors_from_podio():
    """
    GET /subcontractors/podio/items?limit=4&format=raw|normalized|extracted
    Parámetros opcionales:
      - offset, all=true|1|yes, view_id, category_mode (solo para normalized)
    """
    try:
        limit = int(request.args.get("limit", 200))
        offset = int(request.args.get("offset", 0))
        fetch_all = str(request.args.get("all", "false")).lower() in ("1", "true", "yes")
        view_id = request.args.get("view_id")
        fmt = (request.args.get("format") or "normalized").lower()
        category_mode = (request.args.get("category_mode") or "both").lower()

        data = podio_list_subcontractors(
            limit=limit, offset=offset, fetch_all=fetch_all, view_id=view_id,
            fmt=fmt, category_mode=category_mode
        )
        return jsonify(data), 200
    except request.HTTPError as e:
        return jsonify({"error": f"Podio API: {e.response.text}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 400
