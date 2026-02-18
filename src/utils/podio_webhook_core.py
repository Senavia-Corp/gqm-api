from flask import request, jsonify
from sqlmodel import select
import requests
from typing import Optional
from src.podio.podio_auth import get_podio_headers
from src.utils.middleware.retries.retries import retry_api
from src.utils.mappers.mapper_aux_functions import is_recent_event
from src.utils.middleware.retries.db_route_retries.add_session import save_with_retry
from src.utils.middleware.retries.db_route_retries.delete_session import delete_with_retry


# Función para activar el webhook:
@retry_api(max_retries=3, backoff=2)
def activate_podio_webhook(hook_id: str, code: str, app_type: str, year: Optional[int] = None):

    url = f"https://api.podio.com/hook/{hook_id}/verify/validate"
    headers = get_podio_headers(app_type, year=year)

    resp = requests.post(url, json={"code": code}, headers=headers)
    resp.raise_for_status()

    print(
        f"✅ Webhook {hook_id} activado correctamente para {app_type} (Año: {year if year else 'N/A'})")


# Función para validar el webhook y parsear los datos
def parse_and_validate_webhook(app_type: str, year: Optional[int] = None):
    app_type = app_type.upper().strip()
    print(f"📩 Webhook recibido para APP: {app_type} | AÑO: {year}")

    data = request.form.to_dict() or request.get_json() or {}
    if not data:
        raw = request.data.decode("utf-8", errors="ignore")
        print(f"⚠️ Payload vacío: {raw}")
        return app_type, None, jsonify({"status": "ok"}), 200

    # print(f"🔹 Datos parseados: {data}")

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
