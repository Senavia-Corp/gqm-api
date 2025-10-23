#======================================== Código para la Base de Datos en Postgresql =================================
from flask import Blueprint, jsonify, request
from sqlalchemy import select
from ..database.db import get_connection
from ..models.JobModel import JobORM

# Mismo patrón que Clients/Subcontractors
job_bp = Blueprint("job_blueprint", __name__, url_prefix="/jobs")

# ---------- GET: lista ----------
@job_bp.get("/")
def list_jobs():
    """
    GET /jobs
    Devuelve todos los jobs (simple).
    Puedes agregar paginación luego con ?limit=&offset=
    """
    s = get_connection()
    rows = s.execute(select(JobORM).order_by(JobORM.project_name.asc())).scalars().all()
    return jsonify([r.to_dict() for r in rows]), 200

# ---------- GET: uno ----------
@job_bp.get("/<id_job>")
def get_job(id_job):
    """
    GET /jobs/<id_job>
    Devuelve un job por ID o 404 si no existe.
    """
    s = get_connection()
    obj = s.get(JobORM, id_job)
    if not obj:
        return jsonify({"message": "Job not found"}), 404
    return jsonify(obj.to_dict()), 200

# ---------- POST: crear ----------
@job_bp.post("/")
def create_job():
    """
    POST /jobs
    Body JSON mínimo esperado:
    {
      "id_job": "J-001",
      ... otros campos opcionales ...
    }
    """
    data = request.get_json(force=True, silent=False)

    # id_job es obligatorio
    if not data.get("id_job"):
        return jsonify({"error": "Missing required fields: id_job"}), 400

    s = get_connection()
    if s.get(JobORM, data["id_job"]):
        return jsonify({"error": "Job with that id_job already exists"}), 409

    obj = JobORM(
        id_job=data["id_job"],
        project_name=data.get("project_name"),
        project_location=data.get("project_location"),
        job_status=data.get("job_status"),
        po_wtn_wo=data.get("po_wtn_wo"),
        service_type=data.get("service_type"),
        date_assigned=data.get("date_assigned"),
        gqm_formula_pricing=data.get("gqm_formula_pricing"),
        gqm_adj_formula_pricing=data.get("gqm_adj_formula_pricing"),
        gqm_target_sold_pricing=data.get("gqm_target_sold_pricing"),
        gqm_premium_in_money=data.get("gqm_premium_in_money"),
        gqm_final_sold_pricing=data.get("gqm_final_sold_pricing"),
        gqm_final_percentage=data.get("gqm_final_percentage"),
        gqm_total_change_orders=data.get("gqm_total_change_orders"),
        id_member=data.get("id_member"),
        id_client=data.get("id_client"),
    )

    s.add(obj)
    s.commit()
    return jsonify(obj.to_dict()), 201

# ---------- PUT: actualizar ----------
@job_bp.put("/<id_job>")
def update_job(id_job):
    """
    PUT /jobs/<id_job>
    Actualiza campos existentes. No cambia el ID.
    """
    data = request.get_json(force=True, silent=False)
    s = get_connection()
    obj = s.get(JobORM, id_job)
    if not obj:
        return jsonify({"message": "Job not found"}), 404

    # Aplica solo campos presentes en el body
    for key in (
        "project_name", "project_location", "job_status", "po_wtn_wo", "service_type",
        "date_assigned", "gqm_formula_pricing", "gqm_adj_formula_pricing",
        "gqm_target_sold_pricing", "gqm_premium_in_money", "gqm_final_sold_pricing",
        "gqm_final_percentage", "gqm_total_change_orders", "id_member", "id_client"
    ):
        if key in data:
            setattr(obj, key, data[key])

    s.commit()
    return jsonify(obj.to_dict()), 200

# ---------- DELETE: eliminar ----------
@job_bp.delete("/<id_job>")
def delete_job(id_job):
    """
    DELETE /jobs/<id_job>
    Elimina por ID si existe.
    """
    s = get_connection()
    obj = s.get(JobORM, id_job)
    if not obj:
        return jsonify({"message": "Job not found"}), 404

    s.delete(obj)
    s.commit()
    return jsonify({"message": f"Job deleted: {id_job}"}), 200


#=============================================== Código de para la conexión y manejo de Podio =================================
from ..models.JobModel import (
    podio_list_jobs,
    podio_create_job_item,
    podio_update_job_item,
    podio_delete_job_item,
)

@job_bp.get("/podio/items")
def jobs_from_podio():
    """
    GET /jobs/podio/items?limit=4&format=raw|normalized|extracted
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

        data = podio_list_jobs(
            limit=limit, offset=offset, fetch_all=fetch_all, view_id=view_id,
            fmt=fmt, category_mode=category_mode
        )
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@job_bp.post("/podio/items")
def jobs_podio_create():
    """
    POST /jobs/podio/items
    Crea un ítem en el App 'Jobs' de Podio.
    Body esperado:
    {
      "fields": { "<external_id>": { ... } },
      "external_id": "opcional",
      "hook": true/false (opcional),
      "silent": true/false (opcional)
    }
    """
    try:
        body = request.get_json(force=True, silent=False)
        fields = body.get("fields")
        if not isinstance(fields, dict) or not fields:
            return jsonify({"error": "Body debe incluir 'fields' (dict) con al menos un campo."}), 400

        external_id = body.get("external_id")
        hook = bool(body.get("hook", True))
        silent = bool(body.get("silent", False))

        created = podio_create_job_item(fields_payload=fields, external_id=external_id, hook=hook, silent=silent)
        return jsonify(created), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@job_bp.patch("/podio/items/<int:item_id>")
def jobs_podio_update(item_id: int):
    """
    PATCH /jobs/podio/items/<item_id>
    Actualiza campos de un ítem en el App 'Jobs' de Podio.
    Body esperado:
    {
      "fields": { "<external_id>": { ... } },
      "hook": true/false (opcional),
      "silent": true/false (opcional)
    }
    """
    try:
        body = request.get_json(force=True, silent=False)
        fields = body.get("fields")
        if not isinstance(fields, dict) or not fields:
            return jsonify({"error": "Body debe incluir 'fields' (dict) con al menos un campo."}), 400

        hook = bool(body.get("hook", True))
        silent = bool(body.get("silent", False))

        updated = podio_update_job_item(item_id=item_id, fields_payload=fields, hook=hook, silent=silent)
        return jsonify(updated), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@job_bp.delete("/podio/items/<int:item_id>")
def jobs_podio_delete(item_id: int):
    """
    DELETE /jobs/podio/items/<item_id>
    Elimina un ítem en el App 'Jobs' de Podio.
    """
    try:
        podio_delete_job_item(item_id=item_id)
        return jsonify({"message": f"Podio Job item deleted: {item_id}"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

