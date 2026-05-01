# ============ Lógica de rutas =================

from flask import Blueprint, request, jsonify, g
from sqlmodel import select
from sqlalchemy.orm import joinedload
from src.database.db_sqlmodel import get_session
from src.models.ChatModel import ChatMessage, ChatMessageCreate
from src.models.MemberModel import Member
from src.models.JobModel import Job
from src.models.AttachmentsModel import Attachments
from src.utils.middleware.exceptions_handler import handle_exceptions, AppException
from src.utils.middleware.auth.routes_protection import require_role
from src.utils.id_generator import generate_custom_id
from src.cloudinary.service import upload_to_cloudinary
import logging

logger = logging.getLogger(__name__)

# Blueprint del Chat:
chat_bp = Blueprint("chat_blueprint", __name__, url_prefix="/chat")

# ── Caché en memoria
_cache: dict = {}


# -------------------RUTAS CRUD-------------------#


# --------------------RUTAS GET-------------------#

@chat_bp.get("/job/<id_job>")
@handle_exceptions()
@require_role("member")
def get_messages(id_job):
    """
    Devuelve mensajes de un job.
    Query param opcional: ?desde_id=MSG001
    Si no viene, devuelve los últimos 50 (carga inicial).
    """
    desde_id = request.args.get("desde_id", None)

    # ✅ Revisa caché primero — sin tocar Neon
    if desde_id and id_job in _cache:
        nuevos = [m for m in _cache[id_job] if m["ID_ChatMessage"] > desde_id]
        if nuevos:
            return jsonify(nuevos), 200

    # Solo va a Neon si el caché no tiene lo que necesita
    with get_session() as session:
        query = (
            select(ChatMessage)
            .options(joinedload(ChatMessage.member), joinedload(ChatMessage.attachments))
            .where(ChatMessage.ID_Job == id_job)
            .order_by(ChatMessage.created_at.asc())
        )
        if desde_id:
            query = query.where(ChatMessage.ID_ChatMessage > desde_id)
        else:
            query = query.limit(50)

        results = session.exec(query).unique().all()

    mensajes = [
        {
            "ID_ChatMessage": m.ID_ChatMessage,
            "content":        m.content,
            "ID_Job":         m.ID_Job,
            "ID_Member":      m.ID_Member,
            "member_name":    m.member.Member_Name if m.member else None,
            "created_at":     m.created_at.isoformat(),
            "attachments": [
                {
                    "ID_Attachment": a.ID_Attachment,
                    "Document_name": a.Document_name,
                    "Link":          a.Link,
                    "Document_type": a.Document_type,
                }
                for a in m.attachments
            ],
        }
        for m in results
    ]

    # Guarda en caché para las próximas consultas
    if id_job not in _cache:
        _cache[id_job] = []
    _cache[id_job] = mensajes

    return jsonify(mensajes), 200


# --------------- RUTAS POST ----------#

@chat_bp.post("/job/<id_job>")
@handle_exceptions()
@require_role("member")
def send_message(id_job):
    """
    Envía un mensaje en el chat de un job.
    El ID del member viene del token JWT — no se pasa en el body.
    """
    current_user_id = g.current_user["id"]

    data = request.get_json()
    validated = ChatMessageCreate.model_validate(data)

    obj = ChatMessage(
        content=validated.content,
        ID_Job=id_job,
        ID_Member=current_user_id,
    )

    with get_session() as session:
        obj.ID_ChatMessage = generate_custom_id(
            session, ChatMessage, "ID_ChatMessage", "MSG"
        )
        session.add(obj)
        session.commit()
        session.refresh(obj)

        # Trae el nombre del member para incluirlo en la respuesta y el caché
        member = session.exec(
            select(Member).where(Member.ID_Member == current_user_id)
        ).first()

    nuevo = {
        "ID_ChatMessage": obj.ID_ChatMessage,
        "content":        obj.content,
        "ID_Job":         obj.ID_Job,
        "ID_Member":      obj.ID_Member,
        "member_name":    member.Member_Name if member else None,
        "created_at":     obj.created_at.isoformat(),
        "attachments":    [],
    }

    # ✅ Agrega al caché sin ir a Neon
    if id_job not in _cache:
        _cache[id_job] = []
    _cache[id_job].append(nuevo)

    logger.info("💬 Mensaje enviado | job=%s member=%s",
                id_job, current_user_id)
    return jsonify(nuevo), 201


# --------------- RUTA UPLOAD ATTACHMENT (LOGBOOK) ----------#

@chat_bp.post("/job/<id_job>/attachment")
@handle_exceptions()
@require_role("member")
def upload_chat_attachment(id_job):
    current_user_id = g.current_user["id"] if hasattr(
        g, "current_user") else "MEM60001"  # TODO: remove fallback

    file = request.files.get("file")
    if not file:
        raise AppException("No se recibió ningún archivo.",
                           "missing_file", 400)

    with get_session() as session:
        job = session.get(Job, id_job)
        if not job:
            raise AppException(
                f"Job {id_job} no encontrado.", "job_not_found", 404)

        job_type = job.Job_type.value if hasattr(
            job.Job_type, "value") else str(job.Job_type)
        folder = f"Jobs/{job_type}/{id_job}/logbook"

        filename = file.filename
        file_bytes = file.read()
        mimetype = file.mimetype or "application/octet-stream"

        cloudinary_result = upload_to_cloudinary(
            file_bytes=file_bytes,
            filename=filename,
            mimetype=mimetype,
            folder=folder,
            tags=f"logbook,{id_job}"
        )

        logger.info("☁️ Archivo subido al logbook | %s → %s",
                    filename, cloudinary_result["secure_url"])

        msg = ChatMessage(
            content=cloudinary_result["original_name"],
            ID_Job=id_job,
            ID_Member=current_user_id,
        )
        msg.ID_ChatMessage = generate_custom_id(
            session, ChatMessage, "ID_ChatMessage", "MSG")
        session.add(msg)
        session.flush()

        att_id = generate_custom_id(
            session, Attachments, "ID_Attachment", "ATT")
        attachment = Attachments(
            ID_Attachment=att_id,
            Document_name=cloudinary_result["original_name"],
            Link=cloudinary_result["secure_url"],
            Document_type=cloudinary_result["format"].lower() or mimetype,
            access_level="logbook",
            ID_Jobs=id_job,
            ID_ChatMessage=msg.ID_ChatMessage,
        )
        session.add(attachment)
        session.commit()
        session.refresh(msg)

    _cache.pop(id_job, None)

    member_name = None
    with get_session() as s:
        member = s.exec(select(Member).where(
            Member.ID_Member == current_user_id)).first()
        if member:
            member_name = member.Member_Name

    nuevo = {
        "ID_ChatMessage": msg.ID_ChatMessage,
        "content":        msg.content,
        "ID_Job":         msg.ID_Job,
        "ID_Member":      msg.ID_Member,
        "member_name":    member_name,
        "created_at":     msg.created_at.isoformat(),
        "attachments": [
            {
                "ID_Attachment": att_id,
                "Document_name": cloudinary_result["original_name"],
                "Link":          cloudinary_result["secure_url"],
                "Document_type": cloudinary_result["format"].lower() or mimetype,
            }
        ],
    }

    logger.info("📎 Attachment logbook creado | job=%s msg=%s att=%s",
                id_job, msg.ID_ChatMessage, att_id)
    return jsonify(nuevo), 201
