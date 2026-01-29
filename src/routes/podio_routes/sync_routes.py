from flask import Blueprint, jsonify, request
from src.podio.sync.sync_clients import sync_clients
from src.podio.sync.sync_pa_mgmt_co import sync_parent_mgmt_company
from src.podio.sync.sync_subcontractors import sync_subc


sync_bp = Blueprint("sync_bp", __name__, url_prefix="/sync_podio")


# RUTA PARA CLIENTS
@sync_bp.post("/clients")
def sync_clients_route():
    try:
        limit = int(request.args.get("limit", 30))
        offset = int(request.args.get("offset", 0))
        dry_run = request.args.get("dry_run", "false").lower() == "true"

        result = sync_clients(
            limit=limit,
            offset=offset,
            dry_run=dry_run
        )

        return jsonify({
            "resource": "clients",
            "message": "Batch de clients ejecutado ✅",
            **result
        }), 200

    except Exception as e:
        return jsonify({
            "resource": "clients",
            "status": "error",
            "error": str(e)
        }), 500


# RUTA PARA PARENT MGMT COMPANY
@sync_bp.post("/parent_mgmt_co")
def sync_parent_mgmt_company_route():
    try:
        sync_parent_mgmt_company()
        return jsonify({
            "message": "App Parent Mgmt Company sync completed ✅"
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# RUTA PARA SUBCONTRACTORS
@sync_bp.post("/subcontractors")
def sync_subc_route():
    try:
        limit = int(request.args.get("limit", 30))
        offset = int(request.args.get("offset", 0))
        dry_run = request.args.get("dry_run", "false").lower() == "true"

        result = sync_subc(
            limit=limit,
            offset=offset,
            dry_run=dry_run
        )

        return jsonify({
            "resource": "subcontractors",
            "message": "Batch de subcontractors ejecutado ✅",
            **result
        }), 200

    except Exception as e:
        return jsonify({
            "resource": "subcontractors",
            "status": "error",
            "error": str(e)
        }), 500
