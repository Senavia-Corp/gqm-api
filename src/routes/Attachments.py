# ======================================== Código para la Base de Datos en Postgresql =================================
import requests
from flask import Blueprint, jsonify, request
from sqlmodel import select
from sqlalchemy.orm import joinedload

from ..database.db_sqlmodel import get_session
from ..models.AttachmentsModel import Attachments, AttachmentsUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.relationships import add_relationships
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger
from ..utils.middleware.auth.routes_protection import require_permission
from ..utils.policy_evaluator import PolicyEvaluator
from flask import g
from src.podio.podio_auth import get_podio_headers
from src.cloudinary.service import upload_to_cloudinary, delete_from_cloudinary, get_resource_type

# Blueprint de Attachments:
attachments_bp = Blueprint("attachments_blueprint",
                           __name__, url_prefix="/attachments")

# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los attachments
@attachments_bp.get("/")
@require_permission(["attachment:read", "attachment:read_members", "attachment:read_technicians"])
@handle_exceptions()
def list_attachments():
    # Filtro opcional: ?access_level=members | technicians
    access_level = request.args.get("access_level", "").strip().lower() or None

    with get_session() as session:
        statement = (
            select(Attachments)
            .options(
                joinedload(Attachments.job),
                joinedload(Attachments.subcontractor),
                joinedload(Attachments.technician)
            )
        )

        if access_level:
            statement = statement.where(
                Attachments.access_level == access_level)

        results = session.exec(statement).unique().all()

        # Filter by folder-level read permission when the user lacks global read
        user_policies = getattr(g, "user_policies", [])
        has_global_read = PolicyEvaluator.evaluate(
            user_policies, "attachment:read")
        if not has_global_read:
            can_read_members = PolicyEvaluator.evaluate(
                user_policies, "attachment:read_members")
            can_read_technicians = PolicyEvaluator.evaluate(
                user_policies, "attachment:read_technicians")
            results = [
                att for att in results
                if (att.access_level == "technicians" and can_read_technicians)
                or (att.access_level != "technicians" and can_read_members)
            ]

        if not results:
            return jsonify("No se han encontrado archivos adjuntos."), 404

        attachments_data = [
            add_relationships(att, ["job", "subcontractor", "technician"])
            for att in results
        ]

        return attachments_data, 200


# Ruta para conseguir un attachment por ID
@attachments_bp.get("/<id_attachment>")
@require_permission(["attachment:read", "attachment:read_members", "attachment:read_technicians"])
@handle_exceptions()
def get_attachment_by_id(id_attachment):

    with get_session() as session:
        statement = (
            select(Attachments)
            .options(
                joinedload(Attachments.job),
                joinedload(Attachments.subcontractor),
                joinedload(Attachments.technician)
            )
            .where(Attachments.ID_Attachment == id_attachment)
        )
        obj = session.exec(statement).unique().first()

        if not obj:
            raise AppException("Attachment no encontrado.",
                               "attachment_not_found", 404)

        # Check folder-specific read permission
        user_policies = getattr(g, "user_policies", [])
        if not PolicyEvaluator.evaluate(user_policies, "attachment:read"):
            folder = obj.access_level or "members"
            folder_action = f"attachment:read_{folder}"
            if not PolicyEvaluator.evaluate(user_policies, folder_action):
                return jsonify({"error": "Forbidden: You do not have permission to read this attachment"}), 403

        attachment_data = add_relationships(
            obj, ["job", "subcontractor", "technician"])

        return jsonify(attachment_data), 200


# --------------- RUTAS POST, PATCH AND DELETE----------#

# UPLOAD (Frontend → Backend)
# --> Flujo: Cloudinary → Podio → DB
@attachments_bp.post("/upload")
@require_permission(["attachment:create", "attachment:create_members", "attachment:create_technicians"])
@handle_exceptions()
def upload_attachment():
    """
    Recibe un archivo desde Next.js.
    Sube a Cloudinary, adjunta en Podio y guarda en DB.

    Form-data esperado:
        - file:         El archivo
        - entity_id:    ID interno en DB (ej: "PAR5147") — deriva entity_type y app_type
        - year:         Año del Job
        - description:  Descripción opcional
        - tag:          Tag opcional (default: "general")
        - access_level: Nivel de acceso/carpeta (ej: "members", "technicians"). Solo aplica para Jobs.
    """
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"

    # ── 1. Validar archivo y campos ──────────────────────────────
    if "file" not in request.files:
        raise AppException("No se encontró el archivo.", "file_missing", 400)

    file = request.files["file"]
    entity_id = request.form.get("entity_id")
    year = request.form.get("year")
    description = request.form.get("description", "")
    tag = request.form.get("tag", "general")
    access_level = request.form.get("access_level", "").strip().lower()

    if not file.filename:
        raise AppException("El archivo no tiene nombre.", "file_no_name", 400)

    if not entity_id:
        raise AppException(
            "entity_id es requerido.",
            "missing_fields", 400
        )

    year = int(year) if year else None

    # ── 1b. Folder-specific create permission check ──────────────
    user_policies = getattr(g, "user_policies", [])
    if not PolicyEvaluator.evaluate(user_policies, "attachment:create"):
        folder_for_check = access_level if access_level in [
            "members", "technicians"] else "members"
        folder_action = f"attachment:create_{folder_for_check}"
        if not PolicyEvaluator.evaluate(user_policies, folder_action):
            return jsonify({"error": f"Forbidden: You do not have permission to upload to the {folder_for_check} folder"}), 403

    # ── 2. Derivar entity_type y app_type del entity_id ──────────
    JOB_PREFIXES = ["QID", "PTL", "PAR"]
    entity_id_upper = entity_id.upper()

    if any(entity_id_upper.startswith(p) for p in JOB_PREFIXES):
        entity_type = "job"
        app_type = next(
            p for p in JOB_PREFIXES if entity_id_upper.startswith(p))
    elif entity_id_upper.startswith("CLI"):
        entity_type = "client"
        app_type = "CLI"
    elif entity_id_upper.startswith("SUBC"):
        entity_type = "subcontractor"
        app_type = "SUBC"
    elif entity_id_upper.startswith("BLGDEP"):
        entity_type = "building_dept"
        app_type = "BLGDEP"
    elif entity_id_upper.startswith("CER"):
        entity_type = "certificate"
        app_type = "CER"
    else:
        raise AppException(
            f"No se pudo determinar el tipo de entidad para: {entity_id}",
            "unknown_entity_type", 400
        )

    # ── 3. Leer archivo ──────────────────────────────────────────
    filename = file.filename
    file_bytes = file.read()
    mimetype = file.mimetype or "application/octet-stream"

    # ── 4. Subir a Cloudinary ────────────────────────────────────
    # Folder base p.ej: Jobs/PAR/PAR5147
    if entity_type == "job":
        folder = f"Jobs/{app_type}/{entity_id}"
        if access_level in ["members", "technicians"]:
            folder = f"{folder}/{access_level}"
        elif access_level:
            folder = f"{folder}/{access_level}"
    elif entity_type == "certificate":
        # Buscar el subcontratista dueño del certificado para anidar la carpeta
        from ..models.CertificateModel import Certificate as CertificateModel
        with get_session() as session_lookup:
            cert_obj = session_lookup.exec(
                select(CertificateModel).where(CertificateModel.ID_Certificate == entity_id)
            ).first()
        if cert_obj and cert_obj.ID_Subcontractor:
            folder = f"SUBC/{cert_obj.ID_Subcontractor}/CER/{entity_id}"
        else:
            folder = f"CER/{entity_id}"
    else:
        folder = f"{app_type}/{entity_id}"

    tags = f"{tag},{entity_id}"

    cloudinary_result = upload_to_cloudinary(
        file_bytes=file_bytes,
        filename=filename,
        mimetype=mimetype,
        folder=folder,
        tags=tags
    )

    logger.info("☁️ Archivo subido a Cloudinary | %s → %s",
                filename, cloudinary_result["secure_url"])

    # ── 5. Buscar podio_item_id internamente y adjuntar en Podio ─
    podio_file_id = None

    if sync_podio:
        from src.models.JobModel import Job

        with get_session() as session_lookup:
            if entity_type == "job":
                entity_obj = session_lookup.exec(
                    select(Job).where(Job.ID_Jobs == entity_id)
                ).first()
            # Agrega más entidades aquí cuando las necesites

        if not entity_obj:
            raise AppException(
                f"Entidad {entity_id} no encontrada en DB.",
                "entity_not_found", 404
            )

        if not entity_obj.podio_item_id:
            raise AppException(
                f"{entity_id} no tiene podio_item_id registrado.",
                "missing_podio_item_id", 400
            )

        podio_item_id = entity_obj.podio_item_id
        headers = get_podio_headers(app_type, year=year)

        # ----------- 🟢 SUBIR ARCHIVO A PODIO
        upload_resp = requests.post(
            "https://api.podio.com/file/",
            headers={"Authorization": headers["Authorization"]},
            files={"source": (filename, file_bytes, mimetype)},
            data={"filename": filename}
        )
        upload_resp.raise_for_status()
        podio_file_id = str(upload_resp.json().get("file_id"))

        # ----------- 🟢 ADJUNTAR AL ITEM EN PODIO
        attach_resp = requests.post(
            f"https://api.podio.com/file/{podio_file_id}/attach",
            headers=headers,
            json={"ref_type": "item", "ref_id": int(podio_item_id)}
        )
        attach_resp.raise_for_status()

        logger.info("📎 Archivo adjuntado en Podio | file_id=%s → item_id=%s",
                    podio_file_id, podio_item_id)

    # ── 6. Guardar en DB ─────────────────────────────────────────
    with get_session() as session:

        # Evitar duplicados por podio_file_id
        if podio_file_id:
            existing = session.exec(
                select(Attachments).where(
                    Attachments.podio_file_id == podio_file_id)
            ).first()
            if existing:
                return jsonify(existing.model_dump()), 200

        new_id = generate_custom_id(
            session, Attachments, "ID_Attachment", "ATT")

        # FK dinámica según entity_type
        fk_kwargs = {}
        if entity_type == "job":
            fk_kwargs["ID_Jobs"] = entity_id
        elif entity_type == "subcontractor":
            fk_kwargs["ID_Subcontractor"] = entity_id
        elif entity_type == "client":
            fk_kwargs["ID_Client"] = entity_id
        elif entity_type == "building_dept":
            fk_kwargs["ID_BldgDept"] = entity_id
        elif entity_type == "certificate":
            fk_kwargs["ID_Certificate"] = entity_id

        # ----------- 💾 GUARDAR EN DB
        attachment = Attachments(
            ID_Attachment=new_id,
            Document_name=cloudinary_result["original_name"],
            Attachment_descr=description,
            Link=cloudinary_result["secure_url"],
            Document_type=cloudinary_result["format"].lower() or mimetype,
            podio_file_id=podio_file_id,
            access_level=access_level or None,
            **fk_kwargs
        )

        save_with_retry(session, attachment)

        logger.info("✅ Attachment creado | attachment_id=%s | entity_id=%s",
                    new_id, entity_id)

        return jsonify({
            "success":         True,
            "attachment":      attachment.model_dump(),
            "cloudinary_url":  cloudinary_result["secure_url"]
        }), 201


# Ruta para actualizar la metadata en DB
@attachments_bp.patch("/<id_attachment>")
@require_permission(["attachment:update", "attachment:update_members", "attachment:update_technicians"])
@handle_exceptions()
def update_attachment(id_attachment):
    data = request.get_json()

    with get_session() as session:
        obj = session.get(Attachments, id_attachment)
        if not obj:
            raise AppException("Attachment no encontrado.",
                               "attachment_not_found", 404)

        # Check folder-specific update permission
        user_policies = getattr(g, "user_policies", [])
        if not PolicyEvaluator.evaluate(user_policies, "attachment:update"):
            folder = obj.access_level or "members"
            folder_action = f"attachment:update_{folder}"
            if not PolicyEvaluator.evaluate(user_policies, folder_action):
                return jsonify({"error": "Forbidden: You do not have permission to edit this attachment"}), 403

        update_att = AttachmentsUpdate.model_validate(data)
        update_data_dict = update_att.model_dump(exclude_unset=True)

        # ----------- 🔄 ACTUALIZAR EN DB
        for key, value in update_data_dict.items():
            setattr(obj, key, value)

        save_with_retry(session, obj)

        logger.info("🔄 Attachment actualizado | attachment_id=%s",
                    id_attachment)

        return jsonify(obj.model_dump()), 200


# Ruta para eliminar un attachment
# --> Flujo: Cloudinary → Podio → DB
@attachments_bp.delete("/<id_attachment>")
@require_permission(["attachment:delete", "attachment:delete_members", "attachment:delete_technicians"])
@handle_exceptions()
def delete_attachment(id_attachment):

    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    app_type = request.args.get("app_type", "").upper()
    year = request.args.get("year")
    year = int(year) if year else None

    with get_session() as session:
        obj = session.get(Attachments, id_attachment)
        if not obj:
            raise AppException("Attachment no encontrado.",
                               "attachment_not_found", 404)

        # Check folder-specific delete permission
        user_policies = getattr(g, "user_policies", [])
        if not PolicyEvaluator.evaluate(user_policies, "attachment:delete"):
            folder = obj.access_level or "members"
            folder_action = f"attachment:delete_{folder}"
            if not PolicyEvaluator.evaluate(user_policies, folder_action):
                return jsonify({"error": "Forbidden: You do not have permission to delete this attachment"}), 403

        # ----------- 🔴 BORRAR EN CLOUDINARY
        if obj.Link:
            try:
                # Extraer public_id de la URL de Cloudinary
                # URL: https://res.cloudinary.com/cloud/image/upload/v123/Jobs/QID/QID51894/archivo.pdf
                # public_id: Jobs/QID/QID51894/archivo
                parts = obj.Link.split("/upload/")
                public_id = parts[1].split("/", 1)[1].rsplit(".", 1)[0]
                resource_type = get_resource_type(obj.Document_type or "")
                deleted = delete_from_cloudinary(public_id, resource_type)

                if deleted:
                    logger.info(
                        "☁️ Archivo eliminado de Cloudinary | public_id=%s", public_id)
                else:
                    logger.warning(
                        "⚠️ No se pudo eliminar de Cloudinary | public_id=%s", public_id)

            except Exception as e:
                # No bloqueamos el delete si falla Cloudinary
                logger.warning(
                    "⚠️ Error al eliminar de Cloudinary | %s", str(e))

        # ----------- 🔴 BORRAR EN PODIO (SI APLICA)
        if sync_podio and obj.podio_file_id:
            try:
                if not app_type:
                    raise AppException(
                        "app_type es requerido cuando sync_podio=true.",
                        "missing_app_type", 400
                    )

                headers = get_podio_headers(app_type, year=year)

                delete_resp = requests.delete(
                    f"https://api.podio.com/file/{obj.podio_file_id}",
                    headers=headers
                )
                delete_resp.raise_for_status()

                logger.info("🗑️ Archivo eliminado de Podio | podio_file_id=%s",
                            obj.podio_file_id)

            except AppException:
                raise
            except Exception:
                logger.exception(
                    "❌ Error eliminando archivo de Podio | podio_file_id=%s",
                    obj.podio_file_id
                )
                raise AppException(
                    "Error al eliminar el archivo de Podio.",
                    "podio_delete_failed", 502
                )

        # ----------- 🔴 BORRAR EN DB
        delete_with_retry(session, obj)

        logger.info("🗑️ Attachment eliminado | attachment_id=%s",
                    id_attachment)

        return jsonify({
            "message": f"Attachment {id_attachment} eliminado correctamente."
        }), 200
