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
from ...podio.services.job_services import podio_jobs_router
from src.utils.mappers.convert_value_podio import convert_value_for_podio
from src.utils.mappers.mapper_aux_functions import register_event
from src.utils.mappers.to_podio.job_relationships import JOB_MEMBER_PODIO_MAP, get_technician_fields
from src.utils.middleware.logs.logs import logger


# ------------------- Link entre Job y Member -------------------#
job_member_bp = Blueprint(
    "job_member", __name__, url_prefix="/job_member")


# Vincular un trabajo con un miembro GQM
@job_member_bp.post("/jobs/<job_id>/members/<member_id>")
def assign_member_to_job(job_id, member_id):
    data = request.get_json(silent=True) or {}
    rol = data.get("rol")
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)

    with get_session() as session:
        job = session.get(Job, job_id)
        member = session.get(Member, member_id)

        if not job or not member:
            return jsonify({"error": "Job or Member not found"}), 404

        existing_link = session.get(
            JobMemberLink, (job_id, member_id))
        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        # ----------- 🔵 CREAR EN DB
        link = JobMemberLink(
            job_id=job_id,
            member_id=member_id,
            rol=rol
        )

        session.add(link)
        session.commit()

        # ----------- 🟢 CREAR EN PODIO (🔄 Enviar PATCH)
        if sync_podio and year:
            podio_service = podio_jobs_router.get_service(
                job_type=job.Job_type, year=year)

            # Buscar la configuración del rol en el mapper
            cfg = JOB_MEMBER_PODIO_MAP.get(job.Job_type, {}).get(rol)
            if not cfg:
                return jsonify(f"No hay mapping de Podio para rol '{rol}' en job_type '{job.Job_type}'")
            else:
                # Escoger el ID correcto según tipo de campo
                value_to_send = member.podio_item_id if cfg["type"] == "app" else member.podio_profile_id
                if value_to_send:
                    podio_service.update_item(
                        int(job.podio_item_id),
                        {cfg["external_id"]: convert_value_for_podio(
                            value_to_send, cfg["type"])}
                    )
                    # Anti-loop: registrar evento
                    register_event(job.podio_item_id)

        return jsonify({
            "status": "Linked 🔗",
            "job_id": job_id,
            "member_id": member_id
        }), 201


# Desvincular un trabajo de un miembro GQM
@job_member_bp.delete("/jobs/<job_id>/members/<member_id>")
def remove_member_from_job(job_id, member_id):
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)

    with get_session() as session:

        # Buscar si existe el link
        link = session.get(
            JobMemberLink,
            (job_id, member_id)  # Clave primaria compuesta
        )

        if not link:
            return jsonify({
                "error": "Relationship does not exist"
            }), 404

        # Guardar info antes de borrar
        job = session.get(Job, job_id)
        rol_to_update = link.rol

        # ----------- 🟢 DELETE EN PODIO (🔄 Enviar PATCH)
        if sync_podio:
            if not year:
                return jsonify({"error": "El parámetro 'year' es obligatorio cuando sync_podio=true"}), 400

            if job and job.podio_item_id and rol_to_update:
                podio_service = podio_jobs_router.get_service(
                    job_type=job.Job_type, year=year)

                cfg = JOB_MEMBER_PODIO_MAP.get(
                    job.Job_type, {}).get(rol_to_update)
                if cfg and cfg.get("external_id"):
                    podio_service.update_item(
                        int(job.podio_item_id),
                        {cfg["external_id"]: []}  # limpiar relación en Podio
                    )
                    register_event(job.podio_item_id)

        # ----------- 🔴 BORRAR EN DB
        session.delete(link)
        session.commit()

        return jsonify({
            "status": "Unlinked ✖️",
            "job_id": job_id,
            "member_id": member_id
        }), 200


# ---------------- Link entre Job y Multiplier ----------------#
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


# Desvincular un trabajo de un multiplicador
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


# ------------------- Link entre Job y Subcontractor -------------------#
job_subcontractor_bp = Blueprint(
    "job_subcontractor", __name__, url_prefix="/job_subcontractor")


# Vincular un trabajo con un subcontratista
@job_subcontractor_bp.post("/jobs/<job_id>/subcontractors/<subcontr_id>")
def assign_subcontractor_to_job(job_id, subcontr_id):
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)

    with get_session() as session:
        job = session.get(Job, job_id)
        subcontractor = session.get(Subcontractor, subcontr_id)

        if not job or not subcontractor:
            return jsonify({"error": "Job or Subcontractor not found"}), 404

        existing_link = session.get(
            JobSubcontractorLink, (job_id, subcontr_id))
        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        # ----------- 🔵 CREAR EN DB
        link = JobSubcontractorLink(
            job_id=job_id,
            subcontr_id=subcontr_id
        )

        session.add(link)
        session.commit()

        # ----------- 🟢 CREAR EN PODIO (🔄 Enviar PATCH)
        if sync_podio and year:
            if not job.podio_item_id or not subcontractor.podio_item_id:
                return jsonify({"error": "Missing Podio IDs"}), 400

            podio_service = podio_jobs_router.get_service(
                job_type=job.Job_type, year=year)

            # Traer el item actual de Podio
            item = podio_service.get_item(int(job.podio_item_id))
            podio_fields_data = item.get("fields", [])

            # Convertimos a dict para acceso rápido por external_id
            current_values = {
                f["external_id"]: f.get("values")
                for f in podio_fields_data
            }

            technician_fields = get_technician_fields(job.Job_type)

            field_to_use = None

            for field in technician_fields:
                if not current_values.get(field):  # vacío o None
                    field_to_use = field
                    break

            if not field_to_use:
                return jsonify({"error": "No available technician slots in Podio"}), 400

            # Enviar relación al primer campo vacío
            podio_service.update_item(
                int(job.podio_item_id),
                {
                    field_to_use: convert_value_for_podio(
                        subcontractor.podio_item_id,
                        "app"
                    )
                }
            )

            register_event(job.podio_item_id)

        return jsonify({
            "status": "Linked 🔗",
            "job_id": job_id,
            "subcontr_id": subcontr_id
        }), 201


# Desvincular un trabajo de un subcontratista
@job_subcontractor_bp.delete("/jobs/<job_id>/subcontractors/<subcontr_id>")
def remove_subcontractor_from_job(job_id, subcontr_id):
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    year = request.args.get("year", type=int)

    with get_session() as session:

        # Buscar si existe el link
        link = session.get(
            JobSubcontractorLink,
            (job_id, subcontr_id)  # Clave primaria compuesta
        )

        if not link:
            return jsonify({
                "error": "Relationship does not exist"
            }), 404

        # ----------- 🟢 DELETE EN PODIO (🔄 Enviar PATCH)
        if sync_podio:
            if not year:
                return jsonify({"error": "El parámetro 'year' es obligatorio cuando sync_podio=true"}), 400

            job = session.get(Job, job_id)
            subcontractor = session.get(Subcontractor, subcontr_id)

            if not job or not subcontractor:
                return jsonify({"error": "Job or Subcontractor not found"}), 404

            if not job.podio_item_id or not subcontractor.podio_item_id:
                return jsonify({"error": "Missing Podio IDs"}), 400

            podio_service = podio_jobs_router.get_service(
                job_type=job.Job_type,
                year=year
            )

            # Traer item actual
            item = podio_service.get_item(int(job.podio_item_id))
            podio_fields_data = item.get("fields", [])

            # Convertir fields a dict
            current_values = {
                f["external_id"]: f.get("values")
                for f in podio_fields_data
            }

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

                # Buscar si el subcontractor está en ese campo
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
                    int(job.podio_item_id),
                    {field_to_clear: []}  # limpiar campo
                )

                register_event(job.podio_item_id)

            else:
                return jsonify({
                    "error": "Subcontractor not found in Podio for this Job. Possible inconsistency between DB and Podio."
                }), 404

        # ----------- 🔴 BORRAR EN DB
        session.delete(link)
        session.commit()

        return jsonify({
            "status": "Unlinked ✖️",
            "job_id": job_id,
            "subcontr_id": subcontr_id
        }), 200


# ------------------- Link entre Job y Payment Unit -------------------#
job_payment_unit_bp = Blueprint(
    "job_payment_unit", __name__, url_prefix="/job_payment_unit")


# Vincular un trabajo con un payment unit
@job_payment_unit_bp.post("/jobs/<job_id>/payment_units/<payment_unit_id>")
def assign_paymentU_to_job(job_id, payment_unit_id):
    with get_session() as session:
        job = session.get(Job, job_id)
        payment_unit = session.get(PaymentUnit, payment_unit_id)

        if not job or not payment_unit:
            return jsonify({"error": "Job or Payment Unit not found"}), 404

        existing_link = session.get(
            JobPaymentULink, (job_id, payment_unit_id))
        if existing_link:
            return jsonify({"status": "Already linked ✔️"}), 200

        link = JobPaymentULink(
            job_id=job_id,
            payment_unit_id=payment_unit_id
        )

        session.add(link)
        session.commit()

        return jsonify({
            "status": "Linked 🔗",
            "job_id": job_id,
            "subcontr_id": payment_unit_id
        }), 201


# Desvincular un trabajo de un payment unit
@job_payment_unit_bp.delete("/jobs/<job_id>/payment_units/<payment_unit_id>")
def remove_paymentU_from_job(job_id, payment_unit_id):
    with get_session() as session:

        # Buscar si existe el link
        link = session.get(
            JobPaymentULink,
            (job_id, payment_unit_id)  # Clave primaria compuesta
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
            "payment_unit_id": payment_unit_id
        }), 200
