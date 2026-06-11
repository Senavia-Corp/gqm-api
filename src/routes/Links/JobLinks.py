from flask import Blueprint, jsonify, request
from ...database.db_sqlmodel import get_session
from ...models.JobModel import Job
from ...models.MemberModel import Member
from ...models.link_models.JobMember import JobMemberLink
from ...models.MultiplierRModel import MultiplierR
from ...models.link_models.JobMultiplierR import JobMultiplierRLink
from ...models.SubcontractorModel import Subcontractor
from ...models.link_models.JobSubcontractor import JobSubcontractorLink
from ...models.PaymentUnitModel import PaymentUnit
from ...models.link_models.JobPaymentU import JobPaymentULink
from ...models.TechnicianModel import Technician
from ...models.link_models.JobTechnician import JobTechnicianLink
from ...podio.services.job_services import podio_jobs_router
from src.utils.mappers.convert_value_podio import convert_value_for_podio
from src.utils.mappers.mapper_aux_functions import register_event
from src.utils.mappers.to_podio.job_relationships import JOB_MEMBER_PODIO_MAP, get_technician_fields
from src.utils.middleware.logs.logs import logger
from src.utils.audit import log_activity, SOURCE_APP
from src.utils.job_calculator import recalculate_and_apply
from sqlmodel import select


# ───────────────────────────── Job ↔ Member ─────────────────────────────────
job_member_bp = Blueprint("job_member", __name__, url_prefix="/job_member")


@job_member_bp.post("/jobs/<job_id>/members/<member_id>")
def assign_member_to_job(job_id, member_id):
    data = request.get_json(silent=True) or {}
    rol = data.get("rol")
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)
    member_id_header = request.headers.get("X-User-Id") or None

    if not rol:
        return jsonify({"error": "'rol' is required in the request body"}), 400

    with get_session() as session:
        job = session.get(Job,    job_id)
        member = session.get(Member, member_id)

        if not job or not member:
            return jsonify({"error": "Job or Member not found"}), 404

        existing_link = session.exec(
            select(JobMemberLink).where(
                JobMemberLink.job_id == job_id,
                JobMemberLink.member_id == member_id,
                JobMemberLink.rol == rol,
            )
        ).first()

        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        link = JobMemberLink(job_id=job_id, member_id=member_id, rol=rol)
        session.add(link)

        if sync_podio and year:
            podio_service = podio_jobs_router.get_service(
                job_type=job.Job_type, year=year)
            cfg = JOB_MEMBER_PODIO_MAP.get(job.Job_type, {}).get(rol)
            if cfg:
                value_to_send = member.podio_item_id if cfg["type"] == "app" else member.podio_profile_id
                if value_to_send:
                    podio_service.update_item(
                        int(job.podio_item_id),
                        {cfg["external_id"]: convert_value_for_podio(
                            value_to_send, cfg["type"])}
                    )
                    register_event(job.podio_item_id)

        log_activity(
            session,
            action="Member linked to Job",
            entity_id=job_id,
            entity_type="Job",
            member_id=member_id_header,
            description=f"Member: {member_id} | Role: {rol}",
            source=SOURCE_APP
        )

        session.commit()
        return jsonify({"status": "Linked 🔗", "job_id": job_id, "member_id": member_id}), 201


@job_member_bp.delete("/jobs/<job_id>/members/<member_id>")
def remove_member_from_job(job_id, member_id):
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)
    rol = request.args.get("rol") or None
    member_id_header = request.headers.get("X-User-Id") or None

    with get_session() as session:
        query = select(JobMemberLink).where(
            JobMemberLink.job_id == job_id,
            JobMemberLink.member_id == member_id,
        )
        if rol:
            query = query.where(JobMemberLink.rol == rol)
        link = session.exec(query).first()

        if not link:
            return jsonify({"error": "Relationship does not exist"}), 404

        job = session.get(Job, job_id)
        rol_to_update = link.rol

        if sync_podio:
            if not year:
                return jsonify({"error": "El parámetro 'year' es obligatorio cuando sync_podio=true"}), 400
            if job and job.podio_item_id and rol_to_update:
                podio_service = podio_jobs_router.get_service(
                    job_type=job.Job_type, year=year)
                cfg = JOB_MEMBER_PODIO_MAP.get(
                    job.Job_type, {}).get(rol_to_update)
                if cfg and cfg.get("external_id"):
                    podio_service.update_item(int(job.podio_item_id), {
                                              cfg["external_id"]: []})
                    register_event(job.podio_item_id)

        session.delete(link)

        log_activity(
            session,
            action="Member unlinked from Job",
            entity_id=job_id,
            entity_type="Job",
            member_id=member_id_header,
            description=f"Member: {member_id} | Role: {rol_to_update}",
            source=SOURCE_APP
        )

        session.commit()
        return jsonify({"status": "Unlinked ✖️", "job_id": job_id, "member_id": member_id}), 200


# ─────────────────────────── Job ↔ Multiplier ───────────────────────────────
job_multiplier_bp = Blueprint(
    "job_multiplier", __name__, url_prefix="/job_multiplier")


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

        link = JobMultiplierRLink(job_id=job_id, multiplier_id=multiplier_id)
        session.add(link)
        session.flush()

        # LOG 1: valor ANTES del recálculo
        print(
            f"[DEBUG] ANTES recalc → Gqm_adj_formula_pricing = {job.Gqm_adj_formula_pricing}")

        recalculate_and_apply(job_id, session)

        # LOG 2: valor en el objeto retornado por recalculate_and_apply
        job_after = session.get(Job, job_id)
        print(
            f"[DEBUG] DESPUÉS recalc (antes commit) → Gqm_adj_formula_pricing = {job_after.Gqm_adj_formula_pricing}")

        session.commit()

        # LOG 3: valor después del commit, re-query limpio
        session.expire_all()
        job_committed = session.exec(
            select(Job).where(Job.ID_Jobs == job_id)).first()
        print(
            f"[DEBUG] DESPUÉS commit → Gqm_adj_formula_pricing = {job_committed.Gqm_adj_formula_pricing}")

        return jsonify({
            "status": "Linked 🔗",
            "job_id": job_id,
            "multiplier_id": multiplier_id,
            "Gqm_adj_formula_pricing": job_committed.Gqm_adj_formula_pricing,
        }), 201


@job_multiplier_bp.delete("/jobs/<job_id>/multipliers/<multiplier_id>")
def remove_multiplier_from_job(job_id, multiplier_id):
    with get_session() as session:
        link = session.get(JobMultiplierRLink, (job_id, multiplier_id))
        if not link:
            return jsonify({"error": "Relationship does not exist"}), 404

        session.delete(link)
        session.flush()
        recalculate_and_apply(job_id, session)
        session.commit()

        # ← NUEVO: refrescar para leer valores recalculados desde la DB
        job = session.exec(select(Job).where(Job.ID_Jobs == job_id)).first()

        return jsonify({
            "status": "Unlinked ✖️",
            "job_id": job_id,
            "multiplier_id": multiplier_id,
            "Gqm_adj_formula_pricing": job.Gqm_adj_formula_pricing if job else None,
        }), 200


# ─────────────────────────── Job ↔ Subcontractor ────────────────────────────
job_subcontractor_bp = Blueprint(
    "job_subcontractor", __name__, url_prefix="/job_subcontractor")


@job_subcontractor_bp.post("/jobs/<job_id>/subcontractors/<subcontr_id>")
def assign_subcontractor_to_job(job_id, subcontr_id):
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)
    member_id_header = request.headers.get("X-User-Id") or None

    with get_session() as session:
        job = session.get(Job,           job_id)
        subcontractor = session.get(Subcontractor, subcontr_id)

        if not job or not subcontractor:
            return jsonify({"error": "Job or Subcontractor not found"}), 404

        existing_link = session.get(
            JobSubcontractorLink, (job_id, subcontr_id))
        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        link = JobSubcontractorLink(job_id=job_id, subcontr_id=subcontr_id)
        session.add(link)

        if sync_podio and year:
            missing = []
            if not job.podio_item_id:
                missing.append(f"Job '{job_id}'")
            if not subcontractor.podio_item_id:
                missing.append(f"Subcontractor '{subcontr_id}'")

            if missing:
                return jsonify({
                    "error": "Missing Podio IDs",
                    "detail": f"The following entities are not synced with Podio: {', '.join(missing)}. Disable Podio sync or sync these entities first."
                }), 400
            podio_service = podio_jobs_router.get_service(
                job_type=job.Job_type, year=year)
            item = podio_service.get_item(int(job.podio_item_id))
            current_values = {f["external_id"]: f.get(
                "values") for f in item.get("fields", [])}
            technician_fields = get_technician_fields(job.Job_type)
            field_to_use = next(
                (f for f in technician_fields if not current_values.get(f)), None)
            if not field_to_use:
                return jsonify({"error": "No available technician slots in Podio"}), 400
            try:
                podio_service.update_item(
                    int(job.podio_item_id),
                    {field_to_use: convert_value_for_podio(
                        subcontractor.podio_item_id, "app")}
                )
            except Exception as e:
                return jsonify({
                    "error": "Podio update failed",
                    "detail": str(e),
                    "field_attempted": field_to_use
                }), 400
            register_event(job.podio_item_id)

        log_activity(
            session,
            action="Subcontractor linked to Job",
            entity_id=subcontr_id,
            entity_type="Subcontractor",
            job_id=job_id,
            member_id=member_id_header,
            description=f"Job: {job_id}",
            source=SOURCE_APP
        )

        session.commit()
        return jsonify({"status": "Linked 🔗", "job_id": job_id, "subcontr_id": subcontr_id}), 201


@job_subcontractor_bp.delete("/jobs/<job_id>/subcontractors/<subcontr_id>")
def remove_subcontractor_from_job(job_id, subcontr_id):
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)
    member_id_header = request.headers.get("X-User-Id") or None

    with get_session() as session:
        link = session.get(JobSubcontractorLink, (job_id, subcontr_id))
        if not link:
            return jsonify({"error": "Relationship does not exist"}), 404

        if sync_podio:
            if not year:
                return jsonify({"error": "El parámetro 'year' es obligatorio cuando sync_podio=true"}), 400
            job = session.get(Job,           job_id)
            subcontractor = session.get(Subcontractor, subcontr_id)
            if not job or not subcontractor:
                return jsonify({"error": "Job or Subcontractor not found"}), 404
            missing = []
            if not job.podio_item_id:
                missing.append(f"Job '{job_id}'")
            if not subcontractor.podio_item_id:
                missing.append(f"Subcontractor '{subcontr_id}'")

            if missing:
                return jsonify({
                    "error": "Missing Podio IDs",
                    "detail": f"The following entities are not synced with Podio: {', '.join(missing)}. Disable Podio sync or sync these entities first."
                }), 400
            podio_service = podio_jobs_router.get_service(
                job_type=job.Job_type, year=year)
            item = podio_service.get_item(int(job.podio_item_id))
            current_values = {f["external_id"]: f.get(
                "values") for f in item.get("fields", [])}
            technician_fields = get_technician_fields(job.Job_type)

            logger.info("🔍 Technician fields para %s: %s",
                        job.Job_type, technician_fields)
            logger.info("🔍 Current values de Podio: %s", current_values)

            field_to_clear = None
            for field in technician_fields:
                values = current_values.get(field)
                logger.info("🔍 Campo: %s | Values: %s", field, values)
                if not values:
                    continue
                for v in values:
                    item_id = v.get("value", {}).get("item_id")
                    logger.info("🔍 item_id en Podio: %s | buscando: %s",
                                item_id, subcontractor.podio_item_id)
                    if item_id and str(item_id) == str(subcontractor.podio_item_id):
                        field_to_clear = field
                        break
                if field_to_clear:
                    break

            if field_to_clear:
                podio_service.update_item(
                    int(job.podio_item_id), {field_to_clear: []})
                register_event(job.podio_item_id)
            else:
                return jsonify({
                    "error": "Subcontractor not found in Podio for this Job. Possible inconsistency between DB and Podio."
                }), 404

        session.delete(link)

        log_activity(
            session,
            action="Subcontractor unlinked from Job",
            entity_id=subcontr_id,
            entity_type="Subcontractor",
            job_id=job_id,
            member_id=member_id_header,
            description=f"Job: {job_id}",
            source=SOURCE_APP
        )

        session.commit()
        return jsonify({"status": "Unlinked ✖️", "job_id": job_id, "subcontr_id": subcontr_id}), 200


# ─────────────────────────── Job ↔ Payment Unit ─────────────────────────────
job_payment_unit_bp = Blueprint(
    "job_payment_unit", __name__, url_prefix="/job_payment_unit")


@job_payment_unit_bp.post("/jobs/<job_id>/payment_units/<payment_unit_id>")
def assign_paymentU_to_job(job_id, payment_unit_id):
    with get_session() as session:
        job = session.get(Job,         job_id)
        payment_unit = session.get(PaymentUnit, payment_unit_id)
        if not job or not payment_unit:
            return jsonify({"error": "Job or Payment Unit not found"}), 404
        existing_link = session.get(JobPaymentULink, (job_id, payment_unit_id))
        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200
        link = JobPaymentULink(job_id=job_id, payment_unit_id=payment_unit_id)
        session.add(link)
        session.commit()
        return jsonify({"status": "Linked 🔗", "job_id": job_id, "subcontr_id": payment_unit_id}), 201


@job_payment_unit_bp.delete("/jobs/<job_id>/payment_units/<payment_unit_id>")
def remove_paymentU_from_job(job_id, payment_unit_id):
    with get_session() as session:
        link = session.get(JobPaymentULink, (job_id, payment_unit_id))
        if not link:
            return jsonify({"error": "Relationship does not exist"}), 404
        session.delete(link)
        session.commit()
        return jsonify({"status": "Unlinked ✖️", "job_id": job_id, "payment_unit_id": payment_unit_id}), 200

# ─────────────────────────── Job ↔ Technician ─────────────────────────────
job_technician_bp = Blueprint(
    "job_technician", __name__, url_prefix="/job_technician")

@job_technician_bp.post("/jobs/<job_id>/technicians/<technician_id>")
def assign_technician_to_job(job_id, technician_id):
    member_id_header = request.headers.get("X-User-Id") or None
    with get_session() as session:
        job = session.get(Job, job_id)
        technician = session.get(Technician, technician_id)
        if not job or not technician:
            return jsonify({"error": "Job or Technician not found"}), 404
            
        existing_link = session.get(JobTechnicianLink, (job_id, technician_id))
        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200
            
        link = JobTechnicianLink(job_id=job_id, technician_id=technician_id)
        session.add(link)
        
        log_activity(
            session,
            action="Technician linked to Job",
            entity_id=technician_id,
            entity_type="Technician",
            job_id=job_id,
            member_id=member_id_header,
            description=f"Job: {job_id}",
            source=SOURCE_APP
        )
        
        session.commit()
        return jsonify({"status": "Linked 🔗", "job_id": job_id, "technician_id": technician_id}), 201

@job_technician_bp.delete("/jobs/<job_id>/technicians/<technician_id>")
def remove_technician_from_job(job_id, technician_id):
    member_id_header = request.headers.get("X-User-Id") or None
    with get_session() as session:
        link = session.get(JobTechnicianLink, (job_id, technician_id))
        if not link:
            return jsonify({"error": "Relationship does not exist"}), 404
            
        session.delete(link)
        
        log_activity(
            session,
            action="Technician unlinked from Job",
            entity_id=technician_id,
            entity_type="Technician",
            job_id=job_id,
            member_id=member_id_header,
            description=f"Job: {job_id}",
            source=SOURCE_APP
        )
        
        session.commit()
        return jsonify({"status": "Unlinked ✖️", "job_id": job_id, "technician_id": technician_id}), 200
