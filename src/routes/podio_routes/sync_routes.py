from flask import Blueprint, jsonify, request
from src.podio.sync.sync_clients import (
    sync_clients,
    sync_client_related_apps,
    sync_client_related_contacts,
    sync_client_related_managers)
from src.podio.sync.sync_pa_mgmt_co import sync_parent_mgmt_company
from src.podio.sync.sync_subcontractors import (
    sync_subc,
    sync_subcontractor_related_skills)
from src.podio.sync.sync_jobs import (
    sync_jobs,
    sync_jobs_relation,
    sync_job_related_members,
    sync_job_related_subcontractor)
from src.podio.services.job_services import podio_jobs_router
from src.podio.sync.sync_orders import sync_job_orders_and_change_orders
from src.utils.mappers.from_podio.jobs_relationships import RELATION_CONFIG
from src.podio.sync.sync_bldg_dept import sync_bldg_dept


# ===============================
# ----------- FASE 1 -----------
# ===============================
sync_phase1_bp = Blueprint("sync_phase1_bp", __name__,
                           url_prefix="/sync_podio/phase1")


# RUTA PARA CLIENTS
@sync_phase1_bp.post("/clients")
def sync_clients_phase1_route():
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
@sync_phase1_bp.post("/parent_mgmt_co")
def sync_parent_mgmt_company_phase1_route():
    try:
        sync_parent_mgmt_company()
        return jsonify({
            "message": "App Parent Mgmt Company sync completed ✅"
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# RUTA PARA SUBCONTRACTORS
@sync_phase1_bp.post("/subcontractors")
def sync_subc_phase1_route():
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


# RUTA PARA JOBS
@sync_phase1_bp.post("/jobs")
def sync_jobs_phase1_route():
    try:
        job_type = request.args.get("job_type")
        year = request.args.get("year")

        if not job_type or not year:
            return jsonify({
                "resource": "jobs",
                "status": "error",
                "error": "job_type y year son obligatorios"
            }), 400

        limit = int(request.args.get("limit", 30))
        offset = int(request.args.get("offset", 0))
        dry_run = request.args.get("dry_run", "false").lower() == "true"

        result = sync_jobs(
            job_type=job_type,
            year=int(year),
            limit=limit,
            offset=offset,
            dry_run=dry_run
        )

        return jsonify({
            "resource": "jobs",
            "message": "Batch de jobs ejecutado ✅",
            **result
        }), 200

    except Exception as e:
        return jsonify({
            "resource": "jobs",
            "status": "error",
            "error": str(e)
        }), 500


# RUTA PARA BUILDING DEPARTMENT
@sync_phase1_bp.post("/building_department")
def sync_building_department_phase1_route():
    try:
        sync_bldg_dept()
        return jsonify({
            "message": "App Building Department sync completed ✅"
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===============================
# ----------- FASE 2 -----------
# ===============================
sync_phase2_bp = Blueprint("sync_phase2_bp", __name__,
                           url_prefix="/sync_podio/phase2")


# RUTA PARA CLIENTS
@sync_phase2_bp.post("/clients")
def sync_clients_phase2_route():
    try:
        limit = int(request.args.get("limit", 30))
        offset = int(request.args.get("offset", 0))
        dry_run = request.args.get("dry_run", "false").lower() == "true"

        apps_result = sync_client_related_apps(
            limit=limit,
            offset=offset,
            dry_run=dry_run
        )

        contacts_result = sync_client_related_contacts(
            limit=limit,
            offset=offset,
            dry_run=dry_run
        )

        managers_result = sync_client_related_managers(
            limit=limit,
            offset=offset,
            dry_run=dry_run
        )

        return jsonify({
            "resource": "clients",
            "phase": 2,
            "message": "FASE 2 de clients ejecutada ✅",
            "batch": {
                "limit": limit,
                "offset": offset,
                "dry_run": dry_run
            },
            "related_apps": apps_result,
            "related_contacts": contacts_result,
            "related_managers": managers_result
        }), 200

    except Exception as e:
        return jsonify({
            "resource": "clients",
            "phase": 2,
            "status": "error",
            "error": str(e)
        }), 500


# RUTA PARA SUBCONTRACTORS
@sync_phase2_bp.post("/subcontractors")
def sync_subc_phase2_route():
    try:
        limit = int(request.args.get("limit", 30))
        offset = int(request.args.get("offset", 0))
        dry_run = request.args.get("dry_run", "false").lower() == "true"

        skills_result = sync_subcontractor_related_skills(
            limit=limit,
            offset=offset,
            dry_run=dry_run
        )

        return jsonify({
            "resource": "subcontractors",
            "phase": 2,
            "message": "FASE 2 de subcontractors ejecutada ✅",
            "batch": {
                "limit": limit,
                "offset": offset,
                "dry_run": dry_run
            },
            "related_skills": skills_result
        }), 200

    except Exception as e:
        return jsonify({
            "resource": "subcontractors",
            "phase": 2,
            "status": "error",
            "error": str(e)
        }), 500


# RUTAS PARA JOBS
# ---- relaciones tipo APP (M:1)
@sync_phase2_bp.post("/jobs/<relation>")
def sync_jobs_relation_route(relation):
    try:
        job_type = request.args.get("job_type")
        year = request.args.get("year")

        if not job_type or not year:
            return jsonify({"error": "job_type y year son obligatorios"}), 400

        config = RELATION_CONFIG.get(relation)

        if not config:
            return jsonify({"error": "Relación no válida"}), 400

        limit = int(request.args.get("limit", 30))
        offset = int(request.args.get("offset", 0))
        dry_run = request.args.get("dry_run", "false").lower() == "true"

        result = sync_jobs_relation(
            job_type=job_type,
            year=int(year),
            target_model=config["model"],
            source_fk_field=config["fk_field"],
            external_id=config["external_id"],
            internal_id_field=config["internal_id"],
            limit=limit,
            offset=offset,
            dry_run=dry_run
        )

        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---- relaciones tipo APP y CONTACT (M:N)
@sync_phase2_bp.post("/jobs")
def sync_jobs_many_to_many_route():
    try:

        job_type = request.args.get("job_type")
        year = request.args.get("year")

        if not job_type or not year:
            return jsonify({
                "error": "job_type y year son obligatorios"
            }), 400

        limit = int(request.args.get("limit", 30))
        offset = int(request.args.get("offset", 0))
        dry_run = request.args.get("dry_run", "false").lower() == "true"

        members_result = sync_job_related_members(
            job_type=job_type,
            year=int(year),
            limit=limit,
            offset=offset,
            dry_run=dry_run
        )

        subcontractors_result = sync_job_related_subcontractor(
            job_type=job_type,
            year=int(year),
            limit=limit,
            offset=offset,
            dry_run=dry_run
        )

        return jsonify({
            "resource": "jobs",
            "phase": 2,
            "job_type": job_type,
            "year": int(year),
            "message": "FASE 2 de jobs ejecutada ✅",
            "batch": {
                "limit": limit,
                "offset": offset,
                "dry_run": dry_run
            },
            "members_mn": members_result,
            "subcontractors_mn": subcontractors_result
        }), 200

    except Exception as e:
        return jsonify({
            "resource": "jobs",
            "phase": 2,
            "status": "error",
            "error": str(e)
        }), 500


# ---- Orders y Change Orders relacionados
@sync_phase2_bp.post("/jobs/orders")
def sync_orders_changeorders():
    try:

        job_type = request.args.get("job_type")
        year = request.args.get("year")

        if not job_type or not year:
            return jsonify({
                "error": "job_type y year son obligatorios"
            }), 400

        limit = int(request.args.get("limit", 30))
        offset = int(request.args.get("offset", 0))
        dry_run = request.args.get("dry_run", "false").lower() == "true"

        result = sync_job_orders_and_change_orders(
            job_type=job_type,
            year=int(year),
            limit=limit,
            offset=offset,
            dry_run=dry_run
        )

        return jsonify({
            "resource": "jobs",
            "phase": 2,
            "module": "orders_changeorders",
            "job_type": job_type,
            "year": int(year),
            "message": "Orders y Change Orders sincronizados ✅",
            "batch": {
                "limit": limit,
                "offset": offset,
                "dry_run": dry_run
            },
            "result": result
        }), 200

    except Exception as e:
        return jsonify({
            "resource": "jobs",
            "phase": 2,
            "module": "orders_changeorders",
            "status": "error",
            "error": str(e)
        }), 500
