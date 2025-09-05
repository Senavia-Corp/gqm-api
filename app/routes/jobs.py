from flask import Blueprint, request, jsonify
from ..controllers.jobs_controller import get_job_by_id

bp = Blueprint("jobs", __name__)

@bp.get("/<job_id>")
def get_job(job_id: str):
    query = request.args.get("query")
    result = get_job_by_id(job_id, query=query)
    return jsonify(result), 200