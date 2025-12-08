from flask import Blueprint, request, jsonify
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.JobModel import Job
from ..models.ClientModel import Client
from ..models.TasksModel import Tasks
from ..utils.get_podio_items import get_podio_item
from ..utils.mappers.from_podio.job_mapper import map_podio_item_to_job
from ..utils.mappers.from_podio.client_mapper import map_podio_item_to_client
from ..utils.mappers.from_podio.tasks_mapper import map_podio_item_to_task
from ..podio.services.job_services import podio_jobs_router
from ..podio.services.client_services import podio_clients_router
from ..podio.services.tasks_services import podio_tasks_router
import requests
from src.podio.podio_auth import get_podio_headers
from src.utils.middleware.retries.retries import retry_api
from src.utils.id_generator import generate_custom_id

import time
recent_created_items = {}  # { item_id: timestamp }

# Un solo Blueprint para todos los webhooks
webhook_bp = Blueprint("webhook", __name__)


# ----------------------------------------
# ---- Webhook de PODIO
# ----------------------------------------
@retry_api(max_retries=3, backoff=2)
def activate_podio_webhook(hook_id: str, code: str, app_type: str):

    url = f"https://api.podio.com/hook/{hook_id}/verify/validate"
    headers = get_podio_headers(app_type)

    resp = requests.post(url, json={"code": code}, headers=headers)
    resp.raise_for_status()

    print(f"✅ Webhook {hook_id} activado correctamente para {app_type}")


@webhook_bp.route("/webhook/podio/<app_type>", methods=["POST"])
def podio_webhook(app_type):
    app_type = app_type.upper().strip()
    print(f"📩 Webhook recibido para APP: {app_type}")

    APP_ROUTER_MAP = {
        "QID": (podio_jobs_router, map_podio_item_to_job, Job, "ID_Jobs"),
        "PTL": (podio_jobs_router, map_podio_item_to_job, Job, "ID_Jobs"),
        "PAR": (podio_jobs_router, map_podio_item_to_job, Job, "ID_Jobs"),
        "CLI": (podio_clients_router, map_podio_item_to_client, Client, "ID_Client"),
        "TASK": (podio_tasks_router, map_podio_item_to_task, Tasks, "ID_Tasks"),
    }

    PREFIX_MAP = {
        "CLI": "CLI",
        "TASK": "TSK",
    }

    APPS_SIN_ID = {"CLI", "TASK"}

    try:
        data = request.form.to_dict()
        if not data:
            raw = request.data.decode("utf-8", errors="ignore")
            print(f"⚠️ Payload vacío: {raw}")
            return jsonify({"status": "ok"}), 200

        print(f"🔹 Datos parseados: {data}")

        # =====================================================
        #   ACTIVACIÓN (hook.verify)
        # =====================================================
        if data.get("type") == "hook.verify":
            hook_id = data.get("hook_id")
            code = data.get("code")
            print(
                f"📩 SOLICITUD DE VERIFICACIÓN: hook_id={hook_id}, code={code}")
            try:
                activate_podio_webhook(hook_id, code, app_type)
            except Exception as e:
                print(f"❌ Error activando webhook: {e}")
                return jsonify({"error": str(e)}), 500
            return jsonify({"status": "hook.verify recibido y activado"}), 200

        item_id = data.get("item_id")

        # =====================================================
        #   PROTECCIÓN ANTI-LOOP
        # =====================================================
        try:
            if item_id:
                created_ts = recent_created_items.get(int(item_id))
                if created_ts:
                    if time.time() - created_ts < 5:
                        print(
                            f"⛔ Ignorando webhook (item recién creado por la app): {item_id}")
                        del recent_created_items[int(item_id)]
                        return jsonify({"status": "ignored"}), 200
                    del recent_created_items[int(item_id)]
        except Exception as e:
            print(f"⚠️ Error comprobando anti-loop: {e}")

        # =====================================================
        #   EVENTOS REALES
        # =====================================================
        if app_type not in APP_ROUTER_MAP:
            print(f"⚠️ App_type no soportado: {app_type}")
            return jsonify({"status": "ok"}), 200

        router, mapper, Model, id_field = APP_ROUTER_MAP[app_type]
        event_type = data.get("type")
        print(f"📩 Evento recibido: {event_type} | Item ID: {item_id}")

        with get_session() as session:
            # 🔹 Solo llamar a Podio si NO es delete
            if event_type != "item.delete":
                podio_item = data.get(
                    "item") or get_podio_item(item_id, app_type)
                item_data = mapper(podio_item, session)

                if app_type in APPS_SIN_ID:
                    prefix = PREFIX_MAP[app_type]
                    new_id = generate_custom_id(
                        session, Model, id_field, prefix)
                    item_data[id_field] = new_id
                    print(f"🆔 ID generado para {Model.__name__}: {new_id}")

                item_unique_id = str(item_data[id_field])
            else:
                # 🔹 Para delete usamos solo el item_id
                item_unique_id = str(item_id)

            # -----------------------------
            # CREATE
            # -----------------------------
            if event_type == "item.create":
                existing = session.exec(select(Model).where(
                    getattr(Model, id_field) == item_unique_id)).first()
                if existing:
                    print(
                        f"⚠️ {Model.__name__} {item_unique_id} ya existe, omitido.")
                else:
                    new_obj = Model(**item_data)
                    session.add(new_obj)
                    session.commit()
                    session.refresh(new_obj)
                    print(f"✅ {Model.__name__} creado: {item_unique_id}")

            # -----------------------------
            # UPDATE
            # -----------------------------
            elif event_type == "item.update":
                existing = session.exec(select(Model).where(
                    getattr(Model, id_field) == item_unique_id)).first()
                if existing:
                    for k, v in item_data.items():
                        setattr(existing, k, v)
                    session.commit()
                    print(f"🔄 {Model.__name__} actualizado: {item_unique_id}")
                else:
                    new_obj = Model(**item_data)
                    session.add(new_obj)
                    session.commit()
                    print(
                        f"🆕 {Model.__name__} creado durante update: {item_unique_id}")

            # -----------------------------
            # DELETE
            # -----------------------------
            elif event_type == "item.delete":
                obj = session.exec(select(Model).where(
                    getattr(Model, "podio_item_id") == item_unique_id)).first()
                if obj:
                    session.delete(obj)
                    session.commit()
                    print(f"🗑️ {Model.__name__} eliminado: {item_id}")
                else:
                    print(f"⚠️ {Model.__name__} {item_id} no existe")

            else:
                print(f"⚠️ Evento no manejado: {event_type}")

    except Exception as e:
        print(f"❌ Error procesando webhook: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok"}), 200
