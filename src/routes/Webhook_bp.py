import traceback
from flask import Blueprint, jsonify, request
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
from src.utils.podio_webhook_core import (
    parse_and_validate_webhook, event_create, event_update,
    event_delete, process_file_change_event)
from src.podio.webhook.client_hook_sync import process_clients_podio
from src.podio.webhook.subc_hook_sync import process_subcs_podio
from src.podio.webhook.jobs_hook_sync import process_jobs_podio
from src.utils.mappers.qbo_aux_functions import MODEL_MAP, QBO_API_NAME
from src.quickbooks.webhook.events import event_email_qbo, event_void_qbo, event_delete_qbo
from src.quickbooks.webhook.functions import validate_qbo_signature, process_single_entity_qbo
from src.utils.audit import log_activity, SOURCE_PODIO
from src.utils.middleware.logs.logs import logger
from src.utils.middleware.auth.routes_protection import require_permission
from src.utils.job_calculator import recalculate_and_apply
from src.services.commission_service import process_job_to_commissions


webhook_bp = Blueprint("webhook", __name__)


@webhook_bp.before_request
def _validate_podio_webhook_token():
    """REG-018: Podio no firma sus webhooks — el ?token= registrado en la URL
    del hook (func_hooks) es la autenticación. Solo aplica a los receptores;
    si PODIO_WEBHOOK_TOKEN no está configurado se acepta con WARNING (hooks
    legado registrados sin token; el cierre definitivo es del cutover)."""
    import hmac as _hmac

    from decouple import config as _env
    from flask import request as _request

    path = _request.path
    if not (path.startswith("/webhook/podio/jobs") or path.startswith("/webhook/podio/others")):
        return None

    expected = _env("PODIO_WEBHOOK_TOKEN", default="")
    if not expected:
        logger.warning("PODIO_WEBHOOK_TOKEN no configurado: webhook %s aceptado sin validar", path)
        return None

    provided = _request.args.get("token", "")
    if not _hmac.compare_digest(provided, expected):
        return jsonify({"error": "invalid webhook token"}), 403
    return None


# ----------------------------------------
# ---- Webhook de PODIO
# ----------------------------------------

@webhook_bp.route("/webhook/podio/others/no_relations/<app_type>", methods=["POST"])
def podio_general_webhook(app_type):

    APP_ROUTER_MAP = {
        "PMC":  (podio_pa_mgmt_co_router, map_podio_item_to_parent_mgmt_co, ParentMgmtCo, "ID_Community_Tracking"),
        "BDEP": (podio_bldg_dept_router, map_podio_item_to_bldg_dept, BuildingDept, "ID_BldgDept")
    }

    try:
        app_type, data, early_resp, status = parse_and_validate_webhook(
            app_type)
        if early_resp:
            return early_resp, status

        item_id = data.get("item_id")
        event_type = data.get("type")

        if app_type not in APP_ROUTER_MAP:
            print(f"⚠️ App_type no soportado: {app_type}")
            return jsonify({"status": "ok"}), 200

        router, mapper, Model, id_field = APP_ROUTER_MAP[app_type]
        print(f"📩 Evento recibido: {event_type} | Item ID: {item_id}")

        entity_type = Model.__name__  # Dinámico: "ParentMgmtCo" o "BuildingDept"

        with get_session() as session:
            existing = None
            if event_type != "item.delete" and event_type != "file.change":
                podio_item = data.get(
                    "item") or get_podio_item(item_id, app_type)
                item_data = mapper(podio_item, session)
                existing = session.exec(
                    select(Model).where(
                        getattr(Model, "podio_item_id") == str(item_id))
                ).first()
                item_unique_id = str(item_data.get(id_field) or item_id)
            else:
                item_unique_id = str(item_id)

            # --- EJECUCIÓN DE EVENTOS ---

            if event_type == "item.create":
                event_create(session=session, Model=Model, item_id=item_id,
                             item_data=item_data, item_unique_id=item_unique_id)
                action = f"{entity_type} created from Podio"
            elif event_type == "item.update":
                event_update(session=session, Model=Model,
                             item_id=item_id, item_data=item_data)
                action = f"{entity_type} updated from Podio"
            elif event_type == "item.delete":
                event_delete(session=session, Model=Model,
                             item_unique_id=item_unique_id)
                action = f"{entity_type} deleted from Podio"

            elif event_type == "file.change":
                updated_entity = session.exec(
                    select(Model).where(Model.podio_item_id == str(item_id))
                ).first()
                if updated_entity:
                    process_file_change_event(
                        session=session,
                        data=data,
                        app_type=app_type,
                        fk_field=id_field,
                        fk_value=getattr(updated_entity, id_field)
                    )
                action = f"File changed in {entity_type} (Podio)"

            # --- REGISTRO EN AUDITORÍA ---
            if item_unique_id:
                log_activity(
                    session,
                    action=action,
                    entity_id=item_unique_id,
                    entity_type=entity_type,
                    source=SOURCE_PODIO,
                    description=f"Podio item_id: {item_id}"
                )

            else:
                print(f"⚠️ Evento no manejado: {event_type}")

            session.commit()

    except Exception as e:
        print(f"❌ Error procesando webhook: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok"}), 200


@webhook_bp.route("/webhook/podio/others/relations/<app_type>", methods=["POST"])
def podio_relations_webhook(app_type):

    APP_ROUTER_MAP = {
        "CLI":  (podio_clients_router, process_clients_podio, Client, "ID_Client"),
        "SUBC": (podio_subc_router, process_subcs_podio, Subcontractor, "ID_Subcontractor")
    }

    try:
        app_type, data, early_resp, status = parse_and_validate_webhook(
            app_type)
        if early_resp:
            return early_resp, status

        if app_type not in APP_ROUTER_MAP:
            print(f"⚠️ App_type no soportado: {app_type}")
            return jsonify({"status": "ok"}), 200

        router, processor, Model, fk_field = APP_ROUTER_MAP[app_type]
        item_id = data.get("item_id")

        event_type = data.get("type")
        print(f"📩 Evento recibido: {event_type} | Item ID: {item_id}")

        entity_type = Model.__name__

        # --- EJECUCIÓN DE EVENTOS ---

        with get_session() as session:
            if event_type in ["item.create", "item.update"]:
                podio_item = data.get(
                    "item") or get_podio_item(item_id, app_type)
                processor(session, podio_item)
            elif event_type == "item.delete":
                event_delete(session=session, Model=Model,
                             item_unique_id=str(item_id))

            elif event_type == "file.change":
                updated_entity = session.exec(
                    select(Model).where(Model.podio_item_id == str(item_id))
                ).first()
                if updated_entity:
                    process_file_change_event(
                        session=session,
                        data=data,
                        app_type=app_type,
                        fk_field=fk_field,
                        fk_value=getattr(updated_entity, fk_field)
                    )

            # Re-fetch para auditoría (obtener el ID real generado o existente)
            obj = session.exec(select(Model).where(
                Model.podio_item_id == str(item_id))).first()
            if obj or event_type == "item.delete":
                eid = getattr(obj, fk_field) if obj else str(item_id)
                log_activity(
                    session,
                    action=f"{entity_type} {event_type.split('.')[-1]}d from Podio",
                    entity_id=eid,
                    entity_type=entity_type,
                    source=SOURCE_PODIO,
                    description=f"Podio item_id: {item_id}"
                )

            else:
                print(f"⚠️ Evento no manejado: {event_type}")

            session.commit()

    except Exception as e:
        print(f"❌ Error procesando webhook: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------------
# Jobs webhook — con auditoría de timeline
# ---------------------------------------------------------------------------------
@webhook_bp.route("/webhook/podio/jobs/<app_type>/<int:year>", methods=["POST"])
def podio_jobs_webhook(app_type, year):

    JOB_TYPES = {"QID", "PTL", "PAR"}

    try:
        app_type, data, early_resp, status = parse_and_validate_webhook(
            app_type, year=year)
        if early_resp:
            return early_resp, status

        if app_type not in JOB_TYPES:
            print(f"⚠️ App_type no soportado: {app_type}")
            return jsonify({"status": "ok"}), 200

        item_id = data.get("item_id")
        event_type = data.get("type")

        print(f"📩 Evento recibido: {event_type} | Item ID: {item_id}")

        with get_session() as session:

            # ── CREATE & UPDATE ───────────────────────────────────────────
            if event_type in ["item.create", "item.update"]:
                item = data.get("item") or get_podio_item(
                    item_id, app_type, year=year)

                # Extraer quien hizo el cambio para timeline
                current_revision = item.get("current_revision", {})
                changed_by = current_revision.get(
                    "created_by", {}).get("name", "Unknown")

                # Snapshot del Job ANTES de procesar (para detectar status change)
                existing_job = session.exec(
                    select(Job).where(Job.podio_item_id == str(item_id))
                ).first()
                old_status = existing_job.Job_status if existing_job else None

                process_jobs_podio(
                    session=session,
                    item=item,
                    app_type=app_type,
                    year=year,
                )

                # Re-fetch para obtener el job_id y el nuevo status
                updated_job = session.exec(
                    select(Job).where(Job.podio_item_id == str(item_id))
                ).first()

                if updated_job:
                    recalculate_and_apply(updated_job.ID_Jobs, session)

                    # --- 💰 TRIGGER DE COMISIONES (LOCAL) ---
                    # Normalizar ambos estados a mayúsculas para la comparación
                    new_status_norm = (updated_job.Job_status or "").upper()
                    old_status_norm = (old_status or "").upper()

                    # Comparación contra "PAID" una sola vez
                    if new_status_norm == "PAID" and old_status_norm != "PAID":
                        print(
                            f"💰 [Podio Sync] Detectado cambio a PAID para Job {updated_job.ID_Jobs}. Procesando comisiones...")
                        process_job_to_commissions(updated_job, session)

                    is_create = event_type == "item.create"
                    action = "Job created from Podio" if is_create else "Job updated from Podio"

                    desc_parts = [
                        f"Podio item_id: {item_id}",
                        f"Changed by: {changed_by}"
                    ]
                    if not is_create and old_status != updated_job.Job_status:
                        desc_parts.append(
                            f"Status: {old_status} → {updated_job.Job_status}"
                        )

                    log_activity(
                        session,
                        action=action,
                        entity_id=updated_job.ID_Jobs,
                        entity_type="Job",
                        member_id=None,
                        description="  |  ".join(desc_parts),
                        source=SOURCE_PODIO,
                    )

            # ── DELETE ────────────────────────────────────────────────────
            elif event_type == "item.delete":
                job_to_delete = session.exec(
                    select(Job).where(Job.podio_item_id == str(item_id))
                ).first()
                job_id_for_log = job_to_delete.ID_Jobs if job_to_delete else None

                # Cascada simétrica al DELETE por API (hallazgo cobertura B7):
                # también FinancialDocuments, y desenlazar EstimateCost/
                # Opportunities de las Orders antes de borrarlas (FK sin
                # ondelete). Antes este camino dejaba Bills huérfanas.
                if job_id_for_log:
                    from src.models.FinancialDocModel import FinancialDocument
                    for fdoc in session.exec(select(FinancialDocument).where(
                            FinancialDocument.ID_Jobs == job_id_for_log)).all():
                        session.delete(fdoc)

                event_delete(session=session, Model=Job,
                             item_unique_id=str(item_id))

                orders = session.exec(
                    select(Order).where(Order.job_podio_id == str(item_id))).all()
                _order_ids = [o.ID_Order for o in orders if o.ID_Order]
                if _order_ids:
                    from src.models.EstimateCostModel import EstimateCost
                    from src.models.OpportunitiesModel import Opportunities
                    for _model in (EstimateCost, Opportunities):
                        for row in session.exec(select(_model).where(
                                _model.ID_Order.in_(_order_ids))).all():
                            row.ID_Order = None
                            session.add(row)
                for order in orders:
                    delete_with_retry(session, order)
                if orders:
                    print(
                        f"🗑️ {len(orders)} Orders eliminados para Job {item_id}")

                ch_orders = session.exec(
                    select(ChangeOrder).where(ChangeOrder.job_podio_id == str(item_id))).all()
                for ch_order in ch_orders:
                    delete_with_retry(session, ch_order)
                if ch_orders:
                    print(
                        f"🗑️ {len(ch_orders)} Change Orders eliminados para Job {item_id}")

                log_activity(
                    session,
                    action="Job deleted from Podio",
                    entity_id=job_id_for_log,
                    entity_type="Job",
                    member_id=None,
                    description=f"Podio item_id: {item_id} | Changed by: Unknown",
                    source=SOURCE_PODIO,
                )

            # ── FILE CHANGE ───────────────────────────────────────────────
            elif event_type == "file.change":
                updated_job = session.exec(
                    select(Job).where(Job.podio_item_id == str(item_id))
                ).first()

                if not updated_job:
                    print(
                        f"⚠️ Job con podio_item_id={item_id} no existe en DB.")
                else:
                    # Extraer quien hizo el cambio en file.change
                    item = data.get("item") or get_podio_item(
                        item_id, app_type, year=year)
                    current_revision = item.get("current_revision", {})
                    changed_by = current_revision.get(
                        "created_by", {}).get("name", "Unknown")

                    action_type = data.get("action_type")
                    file_ids = data.get("file_ids", "")

                    process_file_change_event(
                        session=session,
                        data=data,
                        app_type=app_type,
                        year=year,
                        id_jobs=updated_job.ID_Jobs
                    )

                    action_map = {
                        "file_created":  "File added from Podio",
                        "file_deleted":  "File deleted from Podio",
                        "file_replaced": "File replaced from Podio",
                    }

                    log_activity(
                        session,
                        action=action_map.get(
                            action_type, f"File {action_type} from Podio"),
                        entity_id=updated_job.ID_Jobs,
                        entity_type="Job",
                        member_id=None,
                        description=f"Podio item_id: {item_id} | file_ids: {file_ids} | Changed by: {changed_by}",
                        source=SOURCE_PODIO,
                    )

            else:
                print(f"⚠️ Evento no manejado: {event_type}")

            # El commit único al final cubre tanto process_jobs_podio
            # como recalculate_and_apply en la misma transacción
            session.commit()

    except Exception as e:
        print(f"❌ Error procesando webhook: {e}")
        traceback.print_exc()
        
        # Guardar en base de datos para sincronización manual
        try:
            from src.models.PodioFailedSyncModel import PodioFailedSync
            with get_session() as error_session:
                failed_sync = PodioFailedSync(
                    item_id=str(data.get("item_id")) if 'data' in locals() and data else None,
                    hook_type=f"podio.jobs.{app_type}.{year}.{event_type}" if 'app_type' in locals() and 'year' in locals() and 'event_type' in locals() else "unknown",
                    payload=data if 'data' in locals() and data else {},
                    error_message=str(e)
                )
                error_session.add(failed_sync)
                error_session.commit()
                print(f"✅ Falla guardada en podio_failed_syncs")
        except Exception as inner_e:
            print(f"❌ No se pudo guardar la falla en podio_failed_syncs: {inner_e}")
            
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok"}), 200


# ----------------------------------------
# ---- Webhook de Quickbooks
# ----------------------------------------

@webhook_bp.route("/webhook/qbo", methods=["POST"])
def qbo_webhook():
    print("\n🔥 --- QBO WEBHOOK START ---", flush=True)
    try:
        raw_body = request.get_data()
        signature = request.headers.get("intuit-signature")

        if not validate_qbo_signature(raw_body, signature):
            return jsonify({"error": "Invalid signature"}), 401

        payload = request.get_json()
        events = payload if isinstance(payload, list) else [payload]
        print(f"📦 Recibidos {len(events)} evento(s)", flush=True)

        for event in events:
            if "intuitentityid" in event:
                entity_id = event.get("intuitentityid")
                realm_id = event.get("intuitaccountid")
                e_type = event.get("type", "")
                parts = e_type.split(".")
                entity_name = parts[1].capitalize() if len(
                    parts) > 1 else "Unknown"
                operation = parts[2].capitalize() if len(
                    parts) > 2 else "Update"
                _process_event(realm_id, entity_name, entity_id, operation)

        return jsonify({"status": "success"}), 200

    except Exception as e:
        print(f"❌ Error crítico en QBO webhook: {str(e)}", flush=True)
        return jsonify({"error": "Internal server error"}), 500


@webhook_bp.route("/webhook/podio/failed_syncs", methods=["GET"])
@require_permission("admin:sync")
def get_failed_syncs():
    try:
        from src.models.PodioFailedSyncModel import PodioFailedSync
        with get_session() as session:
            failed_syncs = session.exec(select(PodioFailedSync).order_by(PodioFailedSync.created_at.desc())).all()
            return jsonify([f.model_dump() for f in failed_syncs]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@webhook_bp.route("/webhook/podio/failed_syncs/count", methods=["GET"])
@require_permission("admin:sync")
def count_failed_syncs():
    try:
        from src.models.PodioFailedSyncModel import PodioFailedSync
        from sqlalchemy import func
        with get_session() as session:
            count = session.exec(select(func.count(PodioFailedSync.id)).where(PodioFailedSync.resolved == False)).one()
            return jsonify({"count": count}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@webhook_bp.route("/webhook/podio/failed_syncs/<int:id>/resync", methods=["POST"])
@require_permission("admin:sync")
def resync_failed_sync(id):
    try:
        from src.models.PodioFailedSyncModel import PodioFailedSync
        with get_session() as session:
            failed_sync = session.get(PodioFailedSync, id)
            if not failed_sync:
                return jsonify({"error": "Failed sync not found"}), 404
            
            if failed_sync.resolved:
                return jsonify({"status": "Already resolved"}), 200

            # hook_type es podio.jobs.{app_type}.{year}.{event_type}
            parts = failed_sync.hook_type.split('.')
            if len(parts) >= 5 and parts[0] == "podio" and parts[1] == "jobs":
                app_type = parts[2]
                year = int(parts[3])
                event_type = ".".join(parts[4:])
                item_id = failed_sync.item_id
                
                # Re-ejecutar la lógica
                if event_type in ["item.create", "item.update"]:
                    item = failed_sync.payload.get("item") or get_podio_item(item_id, app_type, year=year)
                    
                    existing_job = session.exec(select(Job).where(Job.podio_item_id == str(item_id))).first()
                    old_status = existing_job.Job_status if existing_job else None

                    process_jobs_podio(session=session, item=item, app_type=app_type, year=year)

                    updated_job = session.exec(select(Job).where(Job.podio_item_id == str(item_id))).first()
                    if updated_job:
                        recalculate_and_apply(updated_job.ID_Jobs, session)
                        new_status_norm = (updated_job.Job_status or "").upper()
                        old_status_norm = (old_status or "").upper()

                        if new_status_norm == "PAID" and old_status_norm != "PAID":
                            process_job_to_commissions(updated_job, session)
                            
                elif event_type == "item.delete":
                    event_delete(session=session, Model=Job, item_unique_id=str(item_id))

                    orders = session.exec(select(Order).where(Order.job_podio_id == str(item_id))).all()
                    for order in orders: delete_with_retry(session, order)

                    ch_orders = session.exec(select(ChangeOrder).where(ChangeOrder.job_podio_id == str(item_id))).all()
                    for ch_order in ch_orders: delete_with_retry(session, ch_order)

            # Fallos generados por el propio API (B1): re-ejecutar de verdad,
            # jamás marcar resuelto sin haber reintentado (hallazgo review B1).
            elif failed_sync.hook_type in ("auto_sync_to_podio", "update_job_divergence"):
                from src.utils.podio_job_sync import sync_job_to_podio
                job_id = (failed_sync.payload or {}).get("job_id")
                if not job_id:
                    return jsonify({"error": "payload sin job_id, no se puede reintentar"}), 422
                if not sync_job_to_podio(job_id, session):
                    return jsonify({"error": "el re-sync a Podio volvió a fallar"}), 502

            elif failed_sync.hook_type == "create_job_compensation":
                # Compensación pendiente: borrar el item huérfano en Podio
                from src.podio.services.job_services import podio_jobs_router
                payload = failed_sync.payload or {}
                job_type, year = payload.get("job_type"), payload.get("year")
                if not (job_type and year and failed_sync.item_id):
                    return jsonify({"error": "payload incompleto para compensar"}), 422
                try:
                    podio_jobs_router.get_service(
                        job_type=job_type, year=int(year)).delete_item(int(failed_sync.item_id))
                except Exception as del_err:
                    if "404" not in str(del_err) and "410" not in str(del_err):
                        return jsonify({"error": f"no se pudo borrar el item huérfano: {del_err}"}), 502

            else:
                return jsonify({
                    "error": f"hook_type desconocido: {failed_sync.hook_type} — no se puede reintentar"}), 422

            # Solo si todo fue exitoso se marca como resuelto
            failed_sync.resolved = True
            session.add(failed_sync)
            session.commit()
            
            return jsonify({"status": "ok", "message": "Resync exitoso"}), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@webhook_bp.route("/webhook/podio/failed_syncs/<int:id>", methods=["DELETE"])
@require_permission("admin:sync")
def delete_failed_sync(id):
    try:
        from src.models.PodioFailedSyncModel import PodioFailedSync
        with get_session() as session:
            failed_sync = session.get(PodioFailedSync, id)
            if failed_sync:
                session.delete(failed_sync)
                session.commit()
            return jsonify({"status": "ok"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _process_event(realm_id, entity_name, entity_id, operation) -> bool:
    """Devuelve True si procesó; en fallo persiste el evento en la dead-letter
    (REG-057/REG-118) — Intuit recibe 200 y no reintenta jamás."""
    print(
        f"📩 Procesando: {entity_name} | ID: {entity_id} | Op: {operation}", flush=True)

    clean_entity = entity_name.lower()
    model_class = MODEL_MAP.get(clean_entity)
    api_name = QBO_API_NAME.get(clean_entity, entity_name)

    try:
        if operation in ["Delete", "Deleted"]:
            event_delete_qbo(realm_id, api_name, entity_id)
        elif operation == "Void" and model_class:
            with get_session() as session:
                event_void_qbo(session, model_class, entity_id)
        elif operation in ["Emailed", "Email"] and model_class:
            with get_session() as session:
                event_email_qbo(session, model_class, entity_id)
        else:
            process_single_entity_qbo(
                realm_id=realm_id,
                entity_type=api_name,
                qbo_id=entity_id,
            )
    except Exception as e:
        logger.exception("Error procesando evento QBO %s %s %s", entity_name, entity_id, operation)
        try:
            from src.models.QboFailedEventModel import QboFailedEvent
            from src.utils.error_sanitizer import sanitize_error
            with get_session() as dl_session:
                dl_session.add(QboFailedEvent(
                    realm_id=realm_id, entity_name=entity_name,
                    entity_id=str(entity_id), operation=operation,
                    error_message=sanitize_error(e),
                ))
                dl_session.commit()
        except Exception:
            logger.exception("No se pudo registrar QboFailedEvent")
        return False
    return True


# ── Dead-letter QBO (REG-057/REG-118) ────────────────────────────────────
@webhook_bp.route("/webhook/qbo/failed_events", methods=["GET"])
@require_permission("admin:sync")
def get_qbo_failed_events():
    from src.models.QboFailedEventModel import QboFailedEvent
    with get_session() as session:
        rows = session.exec(
            select(QboFailedEvent).where(QboFailedEvent.resolved == False)  # noqa: E712
            .order_by(QboFailedEvent.created_at.desc())
        ).all()
        return jsonify([r.model_dump(mode="json") for r in rows]), 200


@webhook_bp.route("/webhook/qbo/failed_events/count", methods=["GET"])
@require_permission("admin:sync")
def get_qbo_failed_events_count():
    from sqlalchemy import func as sa_func
    from src.models.QboFailedEventModel import QboFailedEvent
    with get_session() as session:
        count = session.exec(
            select(sa_func.count()).select_from(QboFailedEvent)
            .where(QboFailedEvent.resolved == False)  # noqa: E712
        ).one()
        return jsonify({"count": int(count[0] if isinstance(count, tuple) else count)}), 200


@webhook_bp.route("/webhook/qbo/failed_events/<int:id>/retry", methods=["POST"])
@require_permission("admin:sync")
def retry_qbo_failed_event(id):
    from src.models.QboFailedEventModel import QboFailedEvent
    with get_session() as session:
        failed = session.get(QboFailedEvent, id)
        if not failed:
            return jsonify({"error": "Failed event not found"}), 404
        if failed.resolved:
            return jsonify({"status": "Already resolved"}), 200

    # Reprocesar fuera de la sesión (el handler abre las suyas)
    if not _process_event(failed.realm_id, failed.entity_name,
                          failed.entity_id, failed.operation):
        return jsonify({"error": "El reproceso volvió a fallar"}), 502

    with get_session() as session:
        failed = session.get(QboFailedEvent, id)
        failed.resolved = True
        session.add(failed)
        session.commit()
    return jsonify({"status": "ok", "message": "Evento reprocesado"}), 200


@webhook_bp.route("/webhook/qbo/failed_events/<int:id>", methods=["DELETE"])
@require_permission("admin:sync")
def delete_qbo_failed_event(id):
    from src.models.QboFailedEventModel import QboFailedEvent
    with get_session() as session:
        failed = session.get(QboFailedEvent, id)
        if failed:
            session.delete(failed)
            session.commit()
        return jsonify({"status": "ok"}), 200
