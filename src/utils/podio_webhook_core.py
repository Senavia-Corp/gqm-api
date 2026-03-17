from flask import request, jsonify
from sqlmodel import select
import requests
from typing import Optional
from src.podio.podio_auth import get_podio_headers
from src.utils.middleware.retries.retries import retry_api
from src.utils.mappers.mapper_aux_functions import is_recent_event
from src.utils.middleware.retries.db_route_retries.add_session import save_with_retry
from src.utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from src.utils.id_generator import generate_custom_id
from src.cloudinary.service import upload_to_cloudinary
from src.models.AttachmentsModel import Attachments
from src.models.ClientModel import Client
from src.models.SubcontractorModel import Subcontractor
from src.models.ParentMgmtCoModel import ParentMgmtCo
from src.models.BldgDeptModel import BuildingDept


# ─────────────────────────────────────────────
# Mapa dinámico: app_type → modelo + FK
# Agregar nuevas apps de Podio !!!!
# ─────────────────────────────────────────────
ATTACHMENT_MODEL_MAP = {
    "CLI":  {"model": Client,        "fk": "ID_Client"},
    "SUBC": {"model": Subcontractor, "fk": "ID_Subcontractor"},
    "PMC":  {"model": ParentMgmtCo,  "fk": "ID_Community_Tracking"},
    "BDEP": {"model": BuildingDept,  "fk": "ID_BldgDept"},
}


# ─────────────────────────────────────────────
#            Activación del webhook
# ─────────────────────────────────────────────
@retry_api(max_retries=3, backoff=2)
def activate_podio_webhook(hook_id: str, code: str, app_type: str, year: Optional[int] = None):

    url = f"https://api.podio.com/hook/{hook_id}/verify/validate"
    headers = get_podio_headers(app_type, year=year)

    resp = requests.post(url, json={"code": code}, headers=headers)
    resp.raise_for_status()

    print(
        f"✅ Webhook {hook_id} activado correctamente para {app_type} (Año: {year if year else 'N/A'})")


# ─────────────────────────────────────────────
#       Validación y parseo del webhook
# ─────────────────────────────────────────────
def parse_and_validate_webhook(app_type: str, year: Optional[int] = None):
    app_type = app_type.upper().strip()
    print(f"📩 Webhook recibido para APP: {app_type} | AÑO: {year}")

    data = request.form.to_dict() or request.get_json() or {}
    if not data:
        raw = request.data.decode("utf-8", errors="ignore")
        print(f"⚠️ Payload vacío: {raw}")
        return app_type, None, jsonify({"status": "ok"}), 200

    # ---- ACTIVACIÓN (hook.verify)
    if data.get("type") == "hook.verify":
        hook_id = data.get("hook_id")
        code = data.get("code")
        print(
            f"📩 SOLICITUD DE VERIFICACIÓN: hook_id={hook_id}, code={code}")
        try:
            activate_podio_webhook(hook_id, code, app_type, year=year)
        except Exception as e:
            print(f"❌ Error activando webhook: {e}")
            return app_type, None, jsonify({"error": str(e)}), 500
        return app_type, None, jsonify({"status": "hook.verify recibido y activado"}), 200

    # ---- PREPARACION PARA RECIBIR EVENTOS Y QUE NO SE REPITAN
    item_id = data.get("item_id")

    # ---- Anti-loop: ignorar si el evento es reciente
    if item_id and is_recent_event(item_id):
        return app_type, None, jsonify({"status": "ignored"}), 200

    return app_type, data, None, None


# ─────────────────────────────────────────────
#                Eventos CRUD
# ─────────────────────────────────────────────
# Función para el evento CREATE
def event_create(session, Model, item_id, item_data, item_unique_id):
    existing = session.exec(select(Model).where(
        getattr(Model, "podio_item_id") == str(item_id))).first()
    if existing:
        print(
            f"⚠️ {Model.__name__} {item_unique_id} ya existe, omitido.")
    else:
        new_obj = Model(**item_data)
        save_with_retry(session, new_obj)
        print(f"✅ {Model.__name__} creado.")


# Función para el evento UPDATE
def event_update(session, Model, item_id, item_data):
    existing = session.exec(select(Model).where(
        getattr(Model, "podio_item_id") == str(item_id))).first()
    if existing:
        for k, v in item_data.items():
            setattr(existing, k, v)
        save_with_retry(session, existing)
        print(f"🔄 {Model.__name__} actualizado.")
    else:
        new_obj = Model(**item_data)
        save_with_retry(session, new_obj)
        print(
            f"🆕 {Model.__name__} creado durante update.")


# Función para el evento DELETE
def event_delete(session, Model, item_unique_id):
    obj = session.exec(select(Model).where(
        getattr(Model, "podio_item_id") == item_unique_id)).first()
    if obj:
        delete_with_retry(session, obj)
        print(f"🗑️ {Model.__name__} eliminado.")

    else:
        print(f"⚠️ {Model.__name__} {item_unique_id} no existe")


# ─────────────────────────────────────────────
# Procesamiento de attachments desde Podio
# Flujo: Podio → Cloudinary → DB
# ─────────────────────────────────────────────
def process_item_attachments(
    session,
    files: list,
    app_type: str,
    year: Optional[int] = None,
    id_jobs: Optional[str] = None,
    entity_id: Optional[str] = None,
):
    """
    Procesa archivos adjuntos de cualquier app de Podio.
    - Para Jobs:        pasar id_jobs  (ej: "QID51894")
    - Para otras apps:  pasar entity_id (ID interno en DB)

    Folder en Cloudinary:
    - Jobs:       Jobs/{app_type}/{id_jobs}     → Jobs/QID/QID51894
    - Otras apps: {app_type}/{entity_id}        → CLI/CLI-001
    """
    if not files:
        return

    headers = get_podio_headers(app_type, year=year)

    # Definir folder y FK dinámicamente
    if id_jobs:
        folder = f"Jobs/{app_type}/{id_jobs}"
        fk_field = "ID_Jobs"
        fk_value = id_jobs
    elif entity_id and app_type in ATTACHMENT_MODEL_MAP:
        folder = f"{app_type}/{entity_id}"
        fk_field = ATTACHMENT_MODEL_MAP[app_type]["fk"]
        fk_value = entity_id
    else:
        print(
            f"⚠️ app_type '{app_type}' no está en ATTACHMENT_MODEL_MAP, se omite.")
        return

    for file in files:
        file_id = str(file.get("file_id"))
        filename = file.get("name", f"file_{file_id}")
        description = file.get("description", "") or ""

        # Evitar duplicados
        existing = session.exec(
            select(Attachments).where(Attachments.podio_file_id == file_id)
        ).first()
        if existing:
            print(f"⏭️ {filename} ya existe, se omite.")
            continue

        try:
            # Descargar de Podio
            response = requests.get(
                f"https://api.podio.com/file/{file_id}/raw",
                headers=headers,
                stream=True
            )
            response.raise_for_status()

            mimetype = response.headers.get(
                "Content-Type", "application/octet-stream"
            ).split(";")[0]
            file_bytes = response.content

            # Subir a Cloudinary
            cloudinary_result = upload_to_cloudinary(
                file_bytes=file_bytes,
                filename=filename,
                mimetype=mimetype,
                folder=folder
            )

            # Guardar en DB
            new_id = generate_custom_id(
                session, Attachments, "ID_Attachment", "ATT")

            attachment = Attachments(
                ID_Attachment=new_id,
                Document_name=filename,
                Attachment_descr=description,
                Link=cloudinary_result["secure_url"],
                Document_type=cloudinary_result["format"].lower() or mimetype,
                podio_file_id=file_id,
                **{fk_field: fk_value}
            )

            session.add(attachment)
            print(f"✅ {filename} → {fk_field}: {fk_value}")

        except Exception as e:
            print(f"❌ Error procesando archivo {file_id} ({filename}): {e}")
            continue
