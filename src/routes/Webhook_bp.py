from flask import Blueprint, request, jsonify
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.JobModel import Job
from ..utils.get_podio_items import get_podio_item
from ..utils.mappers.job_mapper import map_podio_item_to_job
import requests
from src.podio.podio_auth import get_podio_headers
from src.utils.middleware.retries import retry_api


# Un solo Blueprint para todos los webhooks
webhook_bp = Blueprint("webhook", __name__)


# ----------------------------------------
# ---- Webhook de PODIO
# ----------------------------------------

@retry_api(max_retries=3, backoff=2)
def activate_podio_webhook(hook_id, code):
    """Valida y activa un webhook en Podio automáticamente."""
    url = f"https://api.podio.com/hook/{hook_id}/verify/validate"  # HTTPS obligatorio
    headers = get_podio_headers()
    payload = {"code": code}
    resp = requests.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    print(f"✅ Webhook {hook_id} activado correctamente")


@webhook_bp.route("/webhook/podio", methods=["POST"])
def podio_webhook():
    try:
        # Podio envía form-data, no JSON
        data = request.form.to_dict()
        if not data:
            raw = request.data.decode("utf-8", errors="ignore")
            print(f"🔹 Payload crudo recibido (vacío): {raw}")
            return jsonify({"status": "ok"}), 200

        print(f"🔹 Datos parseados: {data}")

        # --- Activar automáticamente si es hook.verify
        if data.get("type") == "hook.verify":
            hook_id = data.get("hook_id")
            code = data.get("code")
            print(f"📩 VERIFICACIÓN recibida: hook_id={hook_id}, code={code}")

            try:
                activate_podio_webhook(hook_id, code)
            except Exception as e:
                print(f"❌ No se pudo activar el webhook: {e}")
                return jsonify({"error": str(e)}), 500

            return jsonify({"status": "hook.verify recibido y activado"}), 200

        # --- Eventos reales
        event_type = data.get("type")
        item_id = data.get("item_id")
        print(f"📩 Evento recibido: {event_type} | item_id={item_id}")

        with get_session() as session:

            # CREATE / UPDATE
            if event_type in ("item.create", "item.update"):
                podio_item = data.get("item") or get_podio_item(item_id)
                job_data = map_podio_item_to_job(podio_item)

                job_id = str(job_data.get("ID_Jobs"))

                obj = session.exec(select(Job).where(
                    Job.ID_Jobs == job_id)).first()

                if event_type == "item.create":
                    if obj:
                        print(
                            f"⚠️ Job {job_id} ya existe, omitiendo creación.")
                    else:
                        new_job = Job(**job_data)
                        session.add(new_job)
                        session.commit()
                        session.refresh(new_job)
                        print(f"✅ Nuevo Job creado: {job_id}")

                else:  # update
                    if obj:
                        for k, v in job_data.items():
                            setattr(obj, k, v)
                        session.add(obj)
                        session.commit()
                        session.refresh(obj)
                        print(f"🔄 Job actualizado: {job_id}")
                    else:
                        new_job = Job(**job_data)
                        session.add(new_job)
                        session.commit()
                        session.refresh(new_job)
                        print(f"✅ Nuevo Job creado desde update: {job_id}")

            # DELETE
            elif event_type == "item.delete":
                job_id = str(data.get("item_id"))
                obj = session.exec(select(Job).where(
                    Job.podio_item_id == job_id)).first()
                if obj:
                    session.delete(obj)
                    session.commit()
                    print(f"🗑️ Job eliminado: {job_id}")
                else:
                    print(f"⚠️ Job {job_id} no existe; nada que eliminar.")

            else:
                print(f"⚠️ Evento desconocido o no manejado: {event_type}")

    except Exception as e:
        print("❌ Error procesando webhook:", e)
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok"}), 200


# ----------------------------------------
# ---- Webhook de BUILDERTREND (futuro)
# ----------------------------------------
