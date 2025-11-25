from flask import Blueprint, jsonify
from ..database.db_sqlmodel import get_session
from ..models.JobModel import Job
from ..models.MultiplierRModel import MultiplierR
from ..models.link_models.JobMultiplierR import JobMultiplierRLink

job_multiplier_bp = Blueprint(
    "job_multiplier", __name__, url_prefix="/job_multiplier")

# Vincular un trabajo con un multiplicador


@job_multiplier_bp.post("/jobs/<job_id>/multipliers/<multiplier_id>")
def assign_multiplier_to_job(job_id, multiplier_id):
    with get_session() as session:
        job = session.get(Job, job_id)
        multiplier = session.get(MultiplierR, multiplier_id)

        if not job or not multiplier:
            return jsonify({"error": "Job or MultiplierRange not found"}), 404

        existing_link = session.get(
            JobMultiplierRLink, (job_id, multiplier_id))
        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        link = JobMultiplierRLink(
            job_id=job_id,
            multiplier_id=multiplier_id
        )

        session.add(link)
        session.commit()

        return jsonify({
            "status": "Linked 🔗",
            "job_id": job_id,
            "multiplier_id": multiplier_id
        }), 201


# Desvincular un trabajo con un multiplicador
@job_multiplier_bp.delete("/jobs/<job_id>/multipliers/<multiplier_id>")
def remove_multiplier_from_job(job_id, multiplier_id):
    with get_session() as session:

        # Buscar si existe el link
        link = session.get(
            JobMultiplierRLink,
            (job_id, multiplier_id)  # Clave primaria compuesta
        )

        if not link:
            return jsonify({
                "error": "Relationship does not exist"
            }), 404

        session.delete(link)
        session.commit()

        return jsonify({
            "status": "Unlinked ✖️",
            "job_id": job_id,
            "multiplier_id": multiplier_id
        }), 200
