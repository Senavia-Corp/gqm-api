from flask import Blueprint, request, jsonify
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.JobModel import Job
from ..models.OrderModel import Order
from ..models.ClientModel import Client
from ..models.ParentMgmtCoModel import ParentMgmtCo
from ..models.SubcontractorModel import Subcontractor
from ..models.BldgDeptModel import BuildingDept
from ..utils.get_podio_items import get_podio_item
from ..utils.mappers.from_podio.job_mapper import map_podio_item_to_job
from ..utils.mappers.from_podio.order_mapper import process_podio_order
from ..utils.mappers.from_podio.client_mapper import map_podio_item_to_client
from ..utils.mappers.from_podio.parent_mgmt_co_mapper import map_podio_item_to_parent_mgmt_co
from ..utils.mappers.from_podio.subcontractor_mapper import map_podio_item_to_subc
from ..utils.mappers.from_podio.bldg_dept_mapper import map_podio_item_to_bldg_dept
from ..podio.services.job_services import podio_jobs_router
from ..podio.services.client_services import podio_clients_router
from ..podio.services.pa_mgmt_co_services import podio_pa_mgmt_co_router
from ..podio.services.subcontractor_services import podio_subc_router
from ..podio.services.bldg_dept_services import podio_bldg_dept_router
from src.utils.id_generator import generate_custom_id
from src.utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from src.utils.podio_webhook_core import parse_and_validate_webhook, event_create, event_update, event_delete


# Un solo Blueprint para todos los webhooks
webhook_bp = Blueprint("webhook", __name__)


# ----------------------------------------
# ---- Webhook de PODIO
# ----------------------------------------

# Ruta para todo lo que NO depende de Jobs
@webhook_bp.route("/webhook/podio/others/<app_type>", methods=["POST"])
def podio_general_webhook(app_type):

    APP_ROUTER_MAP = {
        "CLI": (podio_clients_router, map_podio_item_to_client, Client, "ID_Client"),
        "PMC": (podio_pa_mgmt_co_router, map_podio_item_to_parent_mgmt_co, ParentMgmtCo, "ID_Community_Tracking"),
        "SUBC": (podio_subc_router, map_podio_item_to_subc, Subcontractor, "ID_Subcontractor"),
        "BDEP": (podio_bldg_dept_router, map_podio_item_to_bldg_dept, BuildingDept, "ID_BldgDept")}

    PREFIX_MAP = {
        "CLI": "CLI",
        "SUBC": "SUBC", }

    APPS_SIN_ID = {"CLI", "SUBC"}

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

                if app_type in APPS_SIN_ID:
                    existing = session.exec(
                        select(Model).where(
                            getattr(Model, "podio_item_id") == str(item_id)
                        )
                    ).first()

                    if app_type in APPS_SIN_ID and not existing:
                        prefix = PREFIX_MAP[app_type]
                        new_id = generate_custom_id(
                            session=session,
                            model=Model,
                            id_field_name=id_field,
                            prefix=prefix
                        )
                        item_data[id_field] = new_id
                        print(f"🆔 ID generado para {Model.__name__}: {new_id}")

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

    except Exception as e:
        print(f"❌ Error procesando webhook: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok"}), 200


# Ruta para todo lo que depende de Jobs
@webhook_bp.route("/webhook/podio/jobs/<app_type>", methods=["POST"])
def podio_jobs_webhook(app_type):

    APP_ROUTER_MAP = {
        "QID": (podio_jobs_router, map_podio_item_to_job, Job, "ID_Jobs"),
        "PTL": (podio_jobs_router, map_podio_item_to_job, Job, "ID_Jobs"),
        "PAR": (podio_jobs_router, map_podio_item_to_job, Job, "ID_Jobs")
    }

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

                process_podio_order(podio_item, session, event_type)

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

                # Eliminar Orders asociados
                orders = session.exec(select(Order).where(
                    Order.job_podio_id == item_id)).all()
                for order in orders:
                    delete_with_retry(session, order)
                if orders:
                    print(
                        f"🗑️ {len(orders)} Orders eliminados para Job {item_id}")

            else:
                print(f"⚠️ Evento no manejado: {event_type}")

    except Exception as e:
        print(f"❌ Error procesando webhook: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok"}), 200
