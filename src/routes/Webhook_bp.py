from flask import Blueprint, request, jsonify
from urllib.parse import parse_qs
from ..database.db_sqlmodel import get_session
from ..models.JobModel import Job
from ..utils.get_podio_items import get_podio_item
from ..utils.mappers.job_mapper import map_podio_item_to_job


# Un solo Blueprint para todos los webhooks
webhook_bp = Blueprint("webhook", __name__)


# ----------------------------------------
# ---- Webhook de PODIO
# ----------------------------------------

@webhook_bp.route("/webhook/podio", methods=["POST"])
def podio_webhook():
    print("🔹 Llegó un request a /webhook/podio")

    # Leer el payload crudo
    raw_data = request.data.decode("utf-8")
    print(f"🔹 Payload crudo recibido: {raw_data}")

    # Manejar pings de verificación de Podio
    if raw_data.startswith("type=hook.verify"):
        try:
            # Extraer hook_id y code
            params = dict(x.split("=") for x in raw_data.split("&"))
            hook_id = int(params.get("hook_id"))
            code = params.get("code")
            print(
                f"📩 Ping de verificación recibido: hook_id={hook_id}, code={code}")

            # Responder exactamente lo que Podio espera
            return jsonify({
                "type": "hook.verify",
                "hook_id": hook_id,
                "code": code
            }), 200

        except Exception as e:
            print("❌ Error procesando ping:", e)
            return jsonify({"error": str(e)}), 400

    # Intentar parsear JSON normal (eventos reales)
    try:
        data = request.get_json(force=True)
    except Exception as e:
        print("❌ Error parseando JSON:", e)
        return jsonify({"error": str(e)}), 400

    event_type = data.get("type")
    item_id = data.get("item_id")
    print(f"📩 Webhook recibido: {event_type} | item_id={item_id}")

    try:
        with get_session() as session:
            # Obtener item completo desde Podio si no viene en payload
            podio_item = data.get("item")
            if not podio_item:
                podio_item = get_podio_item(item_id)

            # Mapear a formato Job
            job_data = map_podio_item_to_job(podio_item)

            # Manejo de eventos
            if event_type == "item.create":
                existing = session.get(Job, job_data["ID_Jobs"])
                if existing:
                    print(
                        f"⚠️ Job {job_data['ID_Jobs']} ya existe, se omite inserción.")
                else:
                    new_job = Job(**job_data)
                    session.add(new_job)
                    session.commit()
                    session.refresh(new_job)
                    print(f"✅ Nuevo Job creado: {new_job.ID_Jobs}")

            elif event_type == "item.update":
                existing = session.get(Job, job_data["ID_Jobs"])
                if existing:
                    for k, v in job_data.items():
                        setattr(existing, k, v)
                    session.add(existing)
                    session.commit()
                    session.refresh(existing)
                    print(f"🔄 Job actualizado: {existing.ID_Jobs}")
                else:
                    print(
                        f"⚠️ Job {job_data['ID_Jobs']} no existe, creando nuevo...")
                    new_job = Job(**job_data)
                    session.add(new_job)
                    session.commit()
                    session.refresh(new_job)
                    print(f"✅ Nuevo Job creado: {new_job.ID_Jobs}")

            elif event_type == "item.delete":
                existing = session.get(Job, job_data["ID_Jobs"])
                if existing:
                    session.delete(existing)
                    session.commit()
                    print(f"🗑️ Job eliminado: {existing.ID_Jobs}")
                else:
                    print(
                        f"⚠️ Job {job_data['ID_Jobs']} no existe, nada que eliminar.")

            else:
                print(f"⚠️ Evento desconocido: {event_type}")

    except Exception as e:
        print("❌ Error procesando webhook:", e)
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok"}), 200

# ----------------------------------------
# ---- Webhook de BUILDERTREND (futuro)
# ----------------------------------------
