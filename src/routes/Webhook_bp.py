from flask import Blueprint, request, jsonify
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

    try:
        raw = request.data.decode("utf-8", errors="ignore")
        # Debug: payload crudo
        print(f"🔹 Payload crudo recibido: {raw}")

        # --- Caso: Podio envía POST vacío (verificación inicial)
        if not raw.strip():
            print("ℹ️ Webhook de verificación vacío recibido. Enviando 200 OK.")
            return jsonify({"status": "verification-ok"}), 200

        # --- Caso: Podio envía form-encoded verify (type=hook.verify&hook_id=...&code=...)
        if raw.startswith("type=hook.verify"):
            try:
                params = dict(x.split("=", 1) for x in raw.split("&"))
                hook_id = int(params.get("hook_id"))
                code = params.get("code")
                print(
                    f"📩 Ping de verificación (form-encoded): hook_id={hook_id}, code={code}")

                # Respuesta que aceptan ambas variantes (igual que en tu versión previa)
                return jsonify({
                    "type": "hook.verify",
                    "hook_id": hook_id,
                    "code": code
                }), 200
            except Exception as e:
                print("❌ Error procesando ping form-encoded:", e)
                return jsonify({"error": str(e)}), 400

        # --- Intentar parsear JSON normal (eventos reales o verify en JSON)
        try:
            data = request.get_json(force=True)
        except Exception as e:
            print("❌ Error parseando JSON:", e)
            return jsonify({"error": str(e)}), 400

        # Manejo de verify en JSON
        if data.get("type") == "hook.verify":
            # algunos ejemplos de payload tienen { "type": "hook.verify", "hook_id": X, "code": "..." }
            hook_id = data.get("hook_id")
            code = data.get("code")
            print(
                f"📩 Ping de verificación (json): hook_id={hook_id}, code={code}")
            return jsonify({
                "type": "hook.verify",
                "hook_id": hook_id,
                "code": code
            }), 200

        # Eventos reales
        event_type = data.get("type")
        item_id = data.get("item_id")
        print(f"📩 Webhook recibido: {event_type} | item_id={item_id}")

        with get_session() as session:

            # CREATE / UPDATE -> necesitamos el item completo (si no viene, lo traemos)
            if event_type in ("item.create", "item.update"):
                podio_item = data.get("item")
                if not podio_item:
                    # Si falla el GET, catchear abajo
                    podio_item = get_podio_item(item_id)

                # Mapear y persistir
                job_data = map_podio_item_to_job(podio_item)

                # Asumimos que la PK en la tabla es el podio_item_id (ajusta si es diferente)
                existing = session.get(Job, int(item_id))

                if event_type == "item.create":
                    if existing:
                        print(
                            f"⚠️ Job {item_id} ya existe, omitiendo creación.")
                    else:
                        # Asegúrate que job_data incluya podio_item_id o que Job model acepte item_id como PK
                        new_job = Job(**job_data)
                        session.add(new_job)
                        session.commit()
                        session.refresh(new_job)
                        print(
                            f"✅ Nuevo Job creado: {new_job.podio_item_id if hasattr(new_job, 'podio_item_id') else item_id}")

                else:  # item.update
                    if existing:
                        for k, v in job_data.items():
                            setattr(existing, k, v)
                        session.add(existing)
                        session.commit()
                        session.refresh(existing)
                        print(
                            f"🔄 Job actualizado: {existing.podio_item_id if hasattr(existing, 'podio_item_id') else item_id}")
                    else:
                        print(
                            f"⚠️ Job {item_id} no existía, creando nuevo desde update...")
                        new_job = Job(**job_data)
                        session.add(new_job)
                        session.commit()
                        session.refresh(new_job)
                        print(
                            f"✅ Nuevo Job creado: {new_job.podio_item_id if hasattr(new_job, 'podio_item_id') else item_id}")

            # DELETE -> NO intentar GET al item, usar item_id para borrar
            elif event_type == "item.delete":
                # Asumimos que la PK es el podio item id; si no, ajusta la consulta
                existing = session.get(Job, int(item_id))
                if existing:
                    session.delete(existing)
                    session.commit()
                    print(f"🗑️ Job eliminado: {item_id}")
                else:
                    print(
                        f"⚠️ Job {item_id} no existe en la DB; nada que eliminar.")

            else:
                print(f"⚠️ Evento desconocido o no manejado: {event_type}")

    except Exception as e:
        print("❌ Error procesando webhook:", e)
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok"}), 200

# ----------------------------------------
# ---- Webhook de BUILDERTREND (futuro)
# ----------------------------------------
