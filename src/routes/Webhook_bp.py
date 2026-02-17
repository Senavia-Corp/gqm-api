import traceback
from flask import Blueprint, jsonify
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.JobModel import Job
from ..models.OrderModel import Order
from ..models.ChangeOrderModel import ChangeOrder
from ..models.ClientModel import Client
from ..models.ParentMgmtCoModel import ParentMgmtCo
from ..models.SubcontractorModel import Subcontractor
from ..models.BldgDeptModel import BuildingDept
from ..utils.get_podio_items import get_podio_item
from ..utils.mappers.from_podio.parent_mgmt_co_mapper import map_podio_item_to_parent_mgmt_co
from ..utils.mappers.from_podio.bldg_dept_mapper import map_podio_item_to_bldg_dept
from ..podio.services.client_services import podio_clients_router
from ..podio.services.pa_mgmt_co_services import podio_pa_mgmt_co_router
from ..podio.services.subcontractor_services import podio_subc_router
from ..podio.services.bldg_dept_services import podio_bldg_dept_router
from src.utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from src.utils.podio_webhook_core import parse_and_validate_webhook, event_create, event_update, event_delete
from src.podio.webhook.client_hook_sync import process_clients_podio
from src.podio.webhook.subc_hook_sync import process_subcs_podio
from src.podio.webhook.jobs_hook_sync import process_jobs_podio


# Un solo Blueprint para todos los webhooks
webhook_bp = Blueprint("webhook", __name__)


# ----------------------------------------
# ---- Webhook de PODIO
# ----------------------------------------
# ---------------------------------------------------------------------------------
# Ruta para todo lo que NO depende de Jobs y NO trae relaciones
@webhook_bp.route("/webhook/podio/others/no_relations/<app_type>", methods=["POST"])
def podio_general_webhook(app_type):

    APP_ROUTER_MAP = {
        "PMC": (podio_pa_mgmt_co_router, map_podio_item_to_parent_mgmt_co, ParentMgmtCo, "ID_Community_Tracking"),
        "BDEP": (podio_bldg_dept_router, map_podio_item_to_bldg_dept, BuildingDept, "ID_BldgDept")}

    try:
        app_type, data, early_resp, status = parse_and_validate_webhook(
            app_type)
        if early_resp:
            return early_resp, status

        item_id = data.get("item_id")
        event_type = data.get("type")

        # =====================================================
        #   EVENTOS REALES
        # =====================================================
        if app_type not in APP_ROUTER_MAP:
            print(f"⚠️ App_type no soportado: {app_type}")
            return jsonify({"status": "ok"}), 200

        router, mapper, Model, id_field = APP_ROUTER_MAP[app_type]
        print(f"📩 Evento recibido: {event_type} | Item ID: {item_id}")

        with get_session() as session:
            existing = None
            # Solo llamar a Podio si NO es delete
            if event_type != "item.delete":
                podio_item = data.get(
                    "item") or get_podio_item(item_id, app_type)
                item_data = mapper(podio_item, session)

                existing = session.exec(
                    select(Model).where(
                        getattr(Model, "podio_item_id") == str(item_id)
                    )
                ).first()

                item_unique_id = str(item_data.get(id_field) or item_id)

            else:
                # 🔹 Para delete usamos solo el item_id
                item_unique_id = str(item_id)

            # -----------------------------
            # CREATE
            # -----------------------------
            if event_type == "item.create":
                event_create(
                    session=session, Model=Model,
                    item_id=item_id, item_data=item_data,
                    item_unique_id=item_unique_id
                )

            # -----------------------------
            # UPDATE
            # -----------------------------
            elif event_type == "item.update":
                event_update(
                    session=session, Model=Model,
                    item_id=item_id, item_data=item_data
                )

            # -----------------------------
            # DELETE
            # -----------------------------
            elif event_type == "item.delete":
                event_delete(
                    session=session, Model=Model,
                    item_unique_id=item_unique_id
                )

            else:
                print(f"⚠️ Evento no manejado: {event_type}")

            session.commit()

    except Exception as e:
        print(f"❌ Error procesando webhook: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------------
# Ruta para todo lo que NO depende de Jobs y SI trae relaciones
@webhook_bp.route("/webhook/podio/others/relations/<app_type>", methods=["POST"])
def podio_relations_webhook(app_type):

    APP_ROUTER_MAP = {
        "CLI": (podio_clients_router, process_clients_podio, Client),
        "SUBC": (podio_subc_router, process_subcs_podio, Subcontractor),
    }

    try:
        app_type, data, early_resp, status = parse_and_validate_webhook(
            app_type)
        if early_resp:
            return early_resp, status

        if app_type not in APP_ROUTER_MAP:
            print(f"⚠️ App_type no soportado: {app_type}")
            return jsonify({"status": "ok"}), 200

        router, processor, Model = APP_ROUTER_MAP[app_type]

        item_id = data.get("item_id")
        event_type = data.get("type")

        # =====================================================
        #   EVENTOS REALES
        # =====================================================
        print(f"📩 Evento recibido: {event_type} | Item ID: {item_id}")

        with get_session() as session:

            # -----------------------------
            #  ===== CREATE & UPDATE =====
            # -----------------------------
            if event_type in ["item.create", "item.update"]:

                podio_item = data.get(
                    "item") or get_podio_item(item_id, app_type)
                processor(session, podio_item)

            # -----------------------------
            # DELETE
            # -----------------------------
            elif event_type == "item.delete":
                event_delete(
                    session=session, Model=Model,
                    item_unique_id=str(item_id)
                )

            else:
                print(f"⚠️ Evento no manejado: {event_type}")

            session.commit()

    except Exception as e:
        print(f"❌ Error procesando webhook: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------------
# Ruta para todo lo que depende de Jobs
@webhook_bp.route("/webhook/podio/jobs/<app_type>/<int:year>", methods=["POST"])
def podio_jobs_webhook(app_type, year):

    JOB_TYPES = {"QID", "PTL", "PAR"}

    try:
        app_type, data, early_resp, status = parse_and_validate_webhook(
            app_type)
        if early_resp:
            return early_resp, status

        if app_type not in JOB_TYPES:
            print(f"⚠️ App_type no soportado: {app_type}")
            return jsonify({"status": "ok"}), 200

        item_id = data.get("item_id")
        event_type = data.get("type")

        # =====================================================
        #   EVENTOS REALES
        # =====================================================
        print(f"📩 Evento recibido: {event_type} | Item ID: {item_id}")

        with get_session() as session:

            # -----------------------------
            #  ===== CREATE & UPDATE =====
            # -----------------------------
            if event_type in ["item.create", "item.update"]:

                item = data.get(
                    "item") or get_podio_item(item_id, app_type)

                process_jobs_podio(
                    session=session,
                    item=item,
                    app_type=app_type,
                    year=year
                )

            # -----------------------------
            # DELETE
            # -----------------------------
            elif event_type == "item.delete":
                event_delete(
                    session=session, Model=Job,
                    item_unique_id=str(item_id)
                )

                # Eliminar Orders asociados
                orders = session.exec(select(Order).where(
                    Order.job_podio_id == str(item_id))).all()
                for order in orders:
                    delete_with_retry(session, order)
                if orders:
                    print(
                        f"🗑️ {len(orders)} Orders eliminados para Job {item_id}")
                # Eliminar Change Orders asociados
                ch_orders = session.exec(select(ChangeOrder).where(
                    ChangeOrder.job_podio_id == str(item_id))).all()
                for ch_order in ch_orders:
                    delete_with_retry(session, ch_order)
                if ch_orders:
                    print(
                        f"🗑️ {len(ch_orders)} Change Orders eliminados para Job {item_id}")

            else:
                print(f"⚠️ Evento no manejado: {event_type}")

            session.commit()

    except Exception as e:
        print(f"❌ Error procesando webhook: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok"}), 200
