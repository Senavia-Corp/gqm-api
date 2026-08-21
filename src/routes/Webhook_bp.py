import time
import traceback
from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from src.utils.error_sanitizer import sanitize_error
from ..models.JobModel import Job
from ..models.OrderModel import Order
from ..models.ChangeOrderModel import ChangeOrder
from ..models.ClientModel import Client
from ..models.ParentMgmtCoModel import ParentMgmtCo
from ..models.SubcontractorModel import Subcontractor
from ..models.BldgDeptModel import BuildingDept
from ..utils.get_podio_items import get_podio_item, item_de_confianza
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

    # hook.verify va EXENTO del token, y no es un agujero: es la unica forma de
    # que un hook llegue a activarse.
    #
    # Medido el 10-ago-2026 en los logs de gqm-api-dev: Podio DESCARTA el query
    # string al enviar la verificacion. Nuestra propia peticion se registro como
    #   "POST /webhook/podio/jobs/QID/2026?token=d6e3... HTTP/1.1" 500
    # y las cuatro de Podio como
    #   "POST /webhook/podio/jobs/QID/2026 HTTP/1.1" 403
    # Sin exencion, el hook nunca pasa la verificacion, se queda en 'inactive' y
    # NO dispara jamas: re-registrar con token mataba la sync entrante en
    # silencio (el paso 3 del runbook lo habria hecho en produccion).
    #
    # Sigue siendo seguro: la verificacion trae hook_id + code y los validamos
    # contra la API de Podio (/hook/<id>/verify/validate). Un code inventado se
    # rechaza — comprobado: con hook_id=1/code=abc, Podio devuelve 400.
    es_verificacion = (
        (_request.form.get("type") or (_request.get_json(silent=True) or {}).get("type"))
        == "hook.verify"
    )
    if es_verificacion:
        logger.info("webhook %s: hook.verify sin token (Podio no reenvia la query) — se permite", path)
        return None

    # El token va en la RUTA, no en el query: Podio DESCARTA el query string en
    # todas sus entregas. Medido el 10-ago-2026 en los logs de gqm-api-dev — la
    # ruta se conserva y el ?token= no llega:
    #   nuestra peticion   "POST …/jobs/QID/2026?token=d6e3…"  (con query)
    #   Podio hook.verify  "POST …/jobs/QID/2026"              (sin query) → 403
    #   Podio item.update  "POST …/jobs/QID/2026"              (sin query) → 403
    # Con el token en el query, NINGUN hook podia entregar nada: el paso 3 del
    # runbook habria dejado la sync entrante muerta con 403 permanente.
    # Se sigue aceptando el query como respaldo para hooks legado.
    en_ruta = (_request.view_args or {}).get("token") or ""
    provided = en_ruta or _request.args.get("token", "")
    if not _hmac.compare_digest(provided, expected):
        return jsonify({"error": "invalid webhook token"}), 403
    return None


def _fallo_receptor_others(app_type, data, event_type, error):
    """Cierre de los receptores /others: registra y elige el código de estado.

    Los dos contestaban `500` a pelo sin registrar NADA. Dos consecuencias, las
    dos medidas: Podio reintenta las entregas 5xx (y desactiva los hooks que
    fallan de forma persistente, así que un solo item inaplicable puede tumbar
    la sync de toda la app), y el fallo no aparecía en `podio_failed_syncs`, que
    es justo lo que el panel enseña al cliente. El receptor de Jobs ya lo hacía
    bien; esto le da a /others el mismo trato.

    IntegrityError → 200. Una PK o UNIQUE duplicada es determinista: el reintento
    de Podio fallará igual, así que pedirlo solo gasta entregas y arriesga el
    hook. Queda en la dead-letter, que es donde se reconcilia a mano.
    Cualquier otro error → 500, para que Podio SÍ reintente (un corte de red o
    un hipo de la BD sí se arregla solo).
    """
    from sqlalchemy.exc import IntegrityError

    from src.utils.failed_sync import record_failed_sync

    determinista = isinstance(error, IntegrityError)
    item_id = (data or {}).get("item_id")
    try:
        with get_session() as s:
            record_failed_sync(
                s, item_id=item_id,
                hook_type=f"podio.others.{app_type}.{event_type or 'unknown'}",
                payload=data or {}, error=error)
    except Exception:
        logger.exception("no se pudo registrar el fallo del receptor others")

    if determinista:
        logger.error("webhook others/%s item=%s inaplicable (%s) → 200 + dead-letter",
                     app_type, item_id, type(error).__name__)
        return jsonify({"status": "dead_letter", "reason": "inaplicable"}), 200
    return jsonify({"error": str(error)}), 500


# ----------------------------------------
# ---- Webhook de PODIO
# ----------------------------------------

@webhook_bp.route("/webhook/podio/others/no_relations/<app_type>", methods=["POST"])
@webhook_bp.route("/webhook/podio/others/no_relations/<app_type>/<token>", methods=["POST"])
def podio_general_webhook(app_type, token=None):

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
                podio_item = item_de_confianza(data, item_id, app_type)
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
                # app_type => se confirma contra Podio antes de borrar
                event_delete(session=session, Model=Model,
                             item_unique_id=item_unique_id,
                             app_type=app_type)
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
        traceback.print_exc()
        return _fallo_receptor_others(
            app_type, locals().get("data"), locals().get("event_type"), e)

    return jsonify({"status": "ok"}), 200


@webhook_bp.route("/webhook/podio/others/relations/<app_type>", methods=["POST"])
@webhook_bp.route("/webhook/podio/others/relations/<app_type>/<token>", methods=["POST"])
def podio_relations_webhook(app_type, token=None):

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
                podio_item = item_de_confianza(data, item_id, app_type)
                processor(session, podio_item)
            elif event_type == "item.delete":
                event_delete(session=session, Model=Model,
                             item_unique_id=str(item_id),
                             app_type=app_type)

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
        traceback.print_exc()
        return _fallo_receptor_others(
            app_type, locals().get("data"), locals().get("event_type"), e)

    return jsonify({"status": "ok"}), 200


def _webhook_state_converged(event_type, item_id, intentos=1, espera=0.0) -> bool:
    """¿El estado deseado del evento ya se cumple pese al error?

    Podio reintenta y una app puede tener varios hooks activos, así que el
    mismo evento llega duplicado y en paralelo: el perdedor de la carrera
    revienta con UniqueViolation aunque el ganador ya dejó la BD como debía.
    Se consulta en una sesión NUEVA (la del request quedó abortada).

    `intentos` existe porque una sola consulta pierde la carrera al revés: el
    perdedor puede comprobar ANTES de que el ganador haga commit, ver que no
    está, y mandar a la dead-letter un evento que sí acabó bien. Pasó de verdad
    —failed_sync #47, jobs_pkey QID60096 duplicada— y le deja al cliente un
    fallo visible en el panel por algo que no es un fallo. El anti-bucle
    (`is_recent_event`) no lo evita: es un dict EN MEMORIA y en Vercel cada
    entrega concurrente cae en otra lambda, igual que le pasaba al limitador
    de login."""
    if not item_id or event_type not in ("item.create", "item.update", "item.delete"):
        return False
    for i in range(max(1, intentos)):
        if i:
            time.sleep(espera)
        with get_session() as check:
            exists = check.exec(
                select(Job).where(Job.podio_item_id == str(item_id))).first() is not None
        if (not exists if event_type == "item.delete" else exists):
            return True
    return False


def _cascade_delete_job_from_podio(session, item_id, app_type=None, year=None):
    """Cascada del delete de jobs venido de Podio — COMPARTIDA entre el webhook
    y el resync de failed_syncs. Simétrica al DELETE por API (Job.py).

    TODO en SQL bulk (no ORM) para los hijos: idempotente y tolerante a
    carreras — si el delete del panel (sync_podio) y el webhook de Podio
    corren a la vez, el segundo solo afecta 0 filas en vez de reventar con
    StaleDataError sobre filas ya borradas (failed_sync #12, 9-ago). El Job
    se borra al final vía ORM: su colección change_orders ya está vacía y
    sus cascades (tasks/estimate_costs/tlactivity) siguen aplicando.
    Devuelve (job_id, n_orders, n_change_orders) para el log."""
    from sqlalchemy import update as sa_update
    from sqlmodel import delete as sq_delete, or_ as sq_or

    from src.models.EstimateCostModel import EstimateCost
    from src.models.FinancialDocModel import FinancialDocument
    from src.models.OpportunitiesModel import Opportunities
    from src.models.link_models.JobMember import JobMemberLink
    from src.models.link_models.JobMultiplierR import JobMultiplierRLink
    from src.models.link_models.JobPaymentU import JobPaymentULink
    from src.models.link_models.JobSubcontractor import JobSubcontractorLink
    from src.models.link_models.JobTechnician import JobTechnicianLink

    ref = str(item_id)
    job = session.exec(select(Job).where(Job.podio_item_id == ref)).first()
    job_id = job.ID_Jobs if job else None

    order_ids = [o for o in session.exec(
        select(Order.ID_Order).where(Order.job_podio_id == ref)).all() if o]

    # 1. Desenlazar EstimateCost/Opportunities de las orders (FK sin ondelete)
    if order_ids:
        for model in (EstimateCost, Opportunities):
            session.exec(sa_update(model).where(
                model.ID_Order.in_(order_ids)).values(ID_Order=None))

    # 2. Change Orders: por ref de Podio, por sus orders o por el job
    co_conds = [ChangeOrder.job_podio_id == ref]
    if order_ids:
        co_conds.append(ChangeOrder.ID_Order.in_(order_ids))
    if job_id:
        co_conds.append(ChangeOrder.ID_Jobs == job_id)
    n_cos = session.exec(
        sq_delete(ChangeOrder).where(sq_or(*co_conds))).rowcount

    # 3. FinancialDocuments del job o de sus orders
    fd_conds = []
    if job_id:
        fd_conds.append(FinancialDocument.ID_Jobs == job_id)
    if order_ids:
        fd_conds.append(FinancialDocument.ID_Order.in_(order_ids))
    if fd_conds:
        session.exec(sq_delete(FinancialDocument).where(sq_or(*fd_conds)))

    # 4. Orders
    n_orders = session.exec(
        sq_delete(Order).where(Order.job_podio_id == ref)).rowcount

    # 5. Links del job (StaleDataError con pares (job, member) duplicados)
    if job_id:
        for link_model in (JobMemberLink, JobMultiplierRLink, JobPaymentULink,
                           JobSubcontractorLink, JobTechnicianLink):
            session.exec(sq_delete(link_model).where(
                link_model.job_id == job_id))

    # 5b. Purchases y opportunities: NO declaran cascade en JobModel.py, así que
    #     el ORM no las borra — les pone `ID_Jobs` a NULL y quedan flotando sin
    #     dueño y sin ruido. Esa es la huella que hay en producción (9 purchases,
    #     8 change_orders, 31 financial_documents con ID_Jobs NULL). Aquí se
    #     toma la decisión explícitamente en vez de dejársela al default de
    #     SQLAlchemy: son hijas del job y se van con él.
    huerfanos_antes = None
    if job_id:
        from src.utils.borrado_job import desvincular_sin_cascade, sentinela_huerfanos
        huerfanos_antes = sentinela_huerfanos(session)
        desvincular_sin_cascade(session, session.get(Job, job_id))

    # 6. El Job al final (ORM: cascades de tasks/estimate_costs/tlactivity).
    #    Si no hay job (carrera ya resuelta), commit de la limpieza bulk.
    session.expire_all()  # las colecciones cacheadas ya no reflejan la BD
    if job_id:
        # app_type => se confirma contra Podio que el item ya no existe antes de
        # borrar el job. Sin esto, un POST sin autenticar con un item_id
        # cualquiera borraba jobs reales.
        event_delete(session=session, Model=Job, item_unique_id=ref,
                     app_type=app_type, year=year)
    else:
        session.commit()

    if huerfanos_antes is not None:
        from src.utils.borrado_job import sentinela_huerfanos
        despues = sentinela_huerfanos(session)
        if despues != huerfanos_antes:
            # No se revierte aquí (el borrado ya está commiteado por
            # event_delete), pero queda en el log con los números exactos: sin
            # esto las huérfanas solo se descubren meses después contando.
            logger.error(
                "BORRADO DE %s DEJÓ HUÉRFANOS: antes %s, después %s",
                ref, huerfanos_antes, despues)

    return job_id, n_orders, n_cos


# ---------------------------------------------------------------------------------
# Jobs webhook — con auditoría de timeline
# ---------------------------------------------------------------------------------
@webhook_bp.route("/webhook/podio/jobs/<app_type>/<int:year>", methods=["POST"])
@webhook_bp.route("/webhook/podio/jobs/<app_type>/<int:year>/<token>", methods=["POST"])
def podio_jobs_webhook(app_type, year, token=None):

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
                item = item_de_confianza(data, item_id, app_type, year=year)

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
                job_id_for_log, n_orders, n_cos = \
                    _cascade_delete_job_from_podio(session, item_id,
                                                   app_type=app_type, year=year)
                if n_orders or n_cos:
                    print(f"🗑️ {n_orders} Orders y {n_cos} Change Orders "
                          f"eliminados para Job {item_id}")

                # entity_id=None a propósito: el job ya no existe y la FK de
                # tlactivity.ID_Jobs haría que el rastro jamás persistiera
                # (el savepoint de audit se traga el IntegrityError).
                log_activity(
                    session,
                    action="Job deleted from Podio",
                    entity_id=None,
                    entity_type="Job",
                    member_id=None,
                    description=(f"Job: {job_id_for_log or 'desconocido'} | "
                                 f"Podio item_id: {item_id} | Changed by: Unknown"),
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
                    item = item_de_confianza(data, item_id, app_type, year=year)
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

        # Entrega duplicada/concurrente ya convergida: el estado deseado se
        # cumple, así que es un ÉXITO idempotente — nada de 500 (Podio
        # reintentaría) ni de dead-letter (ruido para el cliente).
        try:
            # Una PK duplicada es la firma de la carrera entre entregas: se le
            # dan 3 intentos con 1 s para que el ganador haga commit. Cualquier
            # otro error se comprueba una vez y sigue.
            from sqlalchemy.exc import IntegrityError as _IntegrityError
            reintentos = 3 if isinstance(e, _IntegrityError) else 1
            if _webhook_state_converged(event_type, item_id,
                                        intentos=reintentos, espera=1.0):
                print("✅ Estado ya convergido (entrega duplicada) — 200")
                return jsonify({"status": "ok", "note": "duplicate_delivery"}), 200
        except Exception:
            logger.exception("fallo la comprobacion de convergencia del webhook")

        # Petición malformada (sin item_id: body no-JSON, sonda, escaneo…):
        # es un 400 del cliente, no una falla de sincronización — no ensuciar
        # la dead-letter que el cliente ve en el panel.
        if not ('item_id' in locals() and item_id):
            return jsonify({"error": "payload de webhook inválido"}), 400

        # Guardar en base de datos para sincronización manual
        try:
            from src.models.PodioFailedSyncModel import PodioFailedSync
            with get_session() as error_session:
                failed_sync = PodioFailedSync(
                    item_id=str(data.get("item_id")) if 'data' in locals() and data else None,
                    hook_type=f"podio.jobs.{app_type}.{year}.{event_type}" if 'app_type' in locals() and 'year' in locals() and 'event_type' in locals() else "unknown",
                    payload=data if 'data' in locals() and data else {},
                    # NO `str(e)`: en un IntegrityError SQLAlchemy arrastra
                    # `[SQL: INSERT ...] [parameters: {...}]` con los valores
                    # completos de la fila, y `GET /webhook/podio/failed_syncs`
                    # sirve estas filas enteras por HTTP. Hoy son metadatos de
                    # adjuntos; el dia que falle un INSERT sobre una tabla con
                    # una columna de token, ese token acaba literal en esta
                    # tabla y en una respuesta HTTP. El detalle completo va al
                    # log, que no se sirve al cliente.
                    error_message=sanitize_error(e)
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


_ERRORES_DE_CARRERA = (
    "duplicate key", "UniqueViolation", "IntegrityError",
    "StaleDataError", "expected to update 1 row",
)


def auto_resolver_convergidos() -> int:
    """Cierra las fallas cuyo estado deseado YA se cumple.

    Podio reintenta y una app puede tener varios suscriptores; el perdedor de
    la carrera registra una falla aunque el ganador dejara la BD correcta. Sin
    esto, el panel del cliente muestra «errores de sincronización» que no lo
    son (y que el botón Resync cerraría igualmente). Se aplica SOLO a errores
    típicos de carrera y SOLO si se verifica la convergencia; cualquier otra
    falla se respeta y sigue visible. Deja rastro en el mensaje.
    """
    from src.models.PodioFailedSyncModel import PodioFailedSync

    cerradas = 0
    try:
        with get_session() as session:
            pendientes = session.exec(select(PodioFailedSync).where(
                PodioFailedSync.resolved == False)).all()  # noqa: E712
            for fs in pendientes:
                partes = (fs.hook_type or "").split(".")
                if len(partes) < 5 or partes[1] != "jobs":
                    continue
                event_type = ".".join(partes[4:])
                msg = fs.error_message or ""
                if not any(p in msg for p in _ERRORES_DE_CARRERA):
                    continue
                if not _webhook_state_converged(event_type, fs.item_id):
                    continue
                fs.resolved = True
                fs.error_message = ("[auto-resuelta: entrega duplicada, el "
                                    "estado ya era el correcto] " + msg)[:2000]
                session.add(fs)
                cerradas += 1
            if cerradas:
                session.commit()
                logger.info("🧹 %s fallas de sincronización auto-resueltas "
                            "(entregas duplicadas ya convergidas)", cerradas)
    except Exception as e:  # nunca romper la lectura del panel por esto
        logger.warning("no se pudieron auto-resolver fallas convergidas: %s", e)
    return cerradas


@webhook_bp.route("/webhook/podio/failed_syncs", methods=["GET"])
@require_permission("admin:sync")
def get_failed_syncs():
    try:
        from src.models.PodioFailedSyncModel import PodioFailedSync
        auto_resolver_convergidos()
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
        auto_resolver_convergidos()
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

                # GUARD: solo sabemos reintentar estos tres. `file.change`
                # entraba aqui, no coincidia con NINGUN if de abajo, y caia
                # directo al `resolved = True` del final devolviendo "Resync
                # exitoso" SIN HABER HECHO NADA.
                #
                # Medido en produccion: los 12 registros de agosto son todos
                # `file.change`, 7 figuran resueltos, y los 12 ficheros seguian
                # sin estar. Los updated_at de cinco de ellos son 18:53:10, :12,
                # :13, :14 y :16 del 14-ago: cinco clics, cinco "exitos", cero
                # ficheros recuperados. Mentir es peor que no poder.
                #
                # NO ponerlo como `else:` de la cadena de abajo: quedaria pegado
                # al `except` del bloque item.delete y Python lo leeria como el
                # `else` de un try/except — que se ejecuta cuando NO hay
                # excepcion. Comprobado: asi no dispara nunca.
                if event_type not in ("item.create", "item.update", "item.delete"):
                    return jsonify({
                        "error": f"el resync no sabe reintentar '{event_type}'; "
                                 f"para adjuntos usa POST "
                                 f"/sync_podio/phase2/jobs/attachments/<id_jobs>?year=YYYY",
                        "event_type": event_type,
                        "resuelto": False}), 422
                item_id = failed_sync.item_id
                
                # Re-ejecutar la lógica
                if event_type in ["item.create", "item.update"]:
                    try:
                        item = item_de_confianza(
                            failed_sync.payload, item_id, app_type, year=year)
                    except Exception as podio_err:
                        # 404/410: el item ya no está en Podio (lo borraron
                        # después del fallo). Converger = borrarlo también
                        # aquí; el reintento eterno no arregla nada.
                        if not any(c in str(podio_err) for c in ("404", "410")):
                            raise
                        _cascade_delete_job_from_podio(session, item_id)
                        failed_sync.resolved = True
                        session.add(failed_sync)
                        session.commit()
                        return jsonify({
                            "status": "ok",
                            "message": "El item ya no existe en Podio; se sincronizó "
                                       "el borrado y la falla queda resuelta.",
                        }), 200

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
                    # Misma cascada que el webhook (antes esta rama era la
                    # versión vieja y reintroducía Bills huérfanas al reintentar)
                    _cascade_delete_job_from_podio(session, item_id)

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
