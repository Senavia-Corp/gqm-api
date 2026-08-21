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
from src.cloudinary.service import upload_to_cloudinary, delete_from_cloudinary, get_resource_type
from src.models.AttachmentsModel import Attachments
from src.utils.failed_sync import record_failed_attachment
from src.utils.middleware.logs.logs import logger
from src.models.ClientModel import Client
from src.models.SubcontractorModel import Subcontractor
from src.models.ParentMgmtCoModel import ParentMgmtCo
from src.models.BldgDeptModel import BuildingDept


# (conexion, lectura) en segundos. Sin timeout, un cuelgue de Podio deja la
# transaccion del webhook abierta indefinidamente y con ella todo lo que
# dependa de esa sesion. requests NO trae timeout por defecto.
TIMEOUT_PODIO = (5, 60)


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


def item_sigue_vivo_en_podio(item_id, app_type: str, year: Optional[int] = None):
    """¿El item existe todavía en Podio?  True / False / None (no se pudo saber).

    **Solo un 2xx confirma que sigue vivo.** 404, 410 y también 403 cuentan como
    «no está»: Podio responde 403 para items que no existen, no 404 — medido el
    18-ago-2026 con dos `podio_item_id` fabricados (900048090 y 930017423), los
    dos dieron 403. Tratar el 403 como «no lo sé» bloqueaba borrados legítimos y
    rompía la sincronización de bajas.

    Eso no debilita la defensa. Un `item_id` inventado no tiene fila local, así
    que `event_delete` sale antes sin borrar nada; el ataque exige un item REAL
    y enlazado, y ésos devuelven 2xx, que es justo lo que bloquea.

    5xx o error de red → None: ahí sí hay un item probablemente vivo y no se
    puede confirmar, así que no se borra.
    """
    try:
        resp = requests.get(
            f"https://api.podio.com/item/{item_id}/basic",
            headers=get_podio_headers(app_type, year=year),
            timeout=15,
        )
    except Exception as e:
        print(f"⚠️ No se pudo comprobar el item {item_id} en Podio: {e}")
        return None

    if resp.ok:
        return True
    if resp.status_code in (403, 404, 410):
        return False
    print(f"⚠️ Comprobación de {item_id} devolvió {resp.status_code}")
    return None


# Función para el evento DELETE
def event_delete(session, Model, item_unique_id, app_type: Optional[str] = None,
                 year: Optional[int] = None):
    """Borra la fila local que apunta a un item de Podio ya eliminado.

    **Se confirma contra Podio antes de borrar.** Sin esa confirmación, un
    `POST` con `type: item.delete` y un `item_id` cualquiera borraba esa fila —
    y el endpoint acepta SIN autenticar mientras `PODIO_WEBHOOK_TOKEN` no esté
    configurada (medido el 20-ago-2026: `POST /webhook/podio/jobs/QID/2026` sin
    token devuelve 200, no 403). Es decir: cualquiera con la URL podía borrar
    jobs.

    Falla CERRADO. Si el item sigue vivo, no se borra. Si la comprobación no se
    puede completar (Podio caído, credenciales), tampoco: es preferible dejar una
    fila de más que perder un job por un hipo de red. La entrega legítima que se
    pierda vuelve por el `item.delete` siguiente o por la reconciliación diaria.
    """
    obj = session.exec(select(Model).where(
        getattr(Model, "podio_item_id") == item_unique_id)).first()

    if not obj:
        print(f"⚠️ {Model.__name__} {item_unique_id} no existe")
        return

    if app_type:
        vivo = item_sigue_vivo_en_podio(item_unique_id, app_type, year=year)
        if vivo is True:
            print(f"🛑 {Model.__name__} {item_unique_id} SIGUE en Podio: no se borra")
            return
        if vivo is None:
            print(f"🛑 {Model.__name__} {item_unique_id}: sin confirmar en Podio, no se borra")
            return

    delete_with_retry(session, obj)
    print(f"🗑️ {Model.__name__} eliminado.")


# ─────────────────────────────────────────────
# Procesamiento de file.change desde Podio
# Flujo: Podio → Cloudinary → DB
# ─────────────────────────────────────────────
def process_file_change_event(
    session,
    data: dict,
    app_type: str,
    year: Optional[int] = None,
    id_jobs: Optional[str] = None,
    fk_field: Optional[str] = None,
    fk_value: Optional[str] = None,
):
    """
    Maneja el evento file.change de Podio.
    - file_created: descarga y sube a Cloudinary + DB
    - file_deleted: elimina de Cloudinary y DB
    - file_replaced: elimina el viejo y sube el nuevo

    Para Jobs:        pasar id_jobs
    Para otras apps:  pasar fk_field y fk_value
    """
    action_type = data.get("action_type")
    file_ids = data.get("file_ids", "")
    item_id = data.get("item_id")

    print(
        f"📎 file.change | action={action_type} | file_ids={file_ids} | item_id={item_id}")

    if not file_ids:
        print("⚠️ file.change sin file_ids, se omite.")
        return

    file_id_list = [fid.strip() for fid in file_ids.split(",") if fid.strip()]

    # Definir folder y FK una sola vez
    if id_jobs:
        folder = f"Jobs/{app_type}/{id_jobs}"
        _fk_field = "ID_Jobs"
        _fk_value = id_jobs
    elif fk_field and fk_value:
        folder = f"{app_type}/{fk_value}"
        _fk_field = fk_field
        _fk_value = fk_value
    else:
        print(
            f"⚠️ No se pudo determinar FK para app_type={app_type}, se omite.")
        return

    headers = get_podio_headers(app_type, year=year)

    # Red de seguridad: el registro del fallo lee estas dos en los `except`
    # de las TRES ramas, pero solo la de file_created las asigna. Sin esto,
    # un fallo en file_deleted o file_replaced lanza NameError DENTRO del
    # except — peor que el print que sustituyen. Se reinician ademas en cada
    # iteracion de cada bucle, para que el fallo del fichero N no registre
    # el Cloudinary del fichero N-1.
    cloudinary_result = None
    filename = None

    # ── FILE CREATED ──────────────────────────────────────────────
    if action_type == "file_created":
        for file_id in file_id_list:

            # Deben existir ANTES del try: el registro del fallo los usa, y
            # `cloudinary_result` es lo que distingue "nunca se subio" de
            # "subido a Cloudinary pero no persistido" — esa distincion es la
            # que permite recuperar el fichero sin volver a bajarlo de Podio.
            cloudinary_result = None
            filename = None

            try:
                # El SELECT de dedup va DENTRO del try y con no_autoflush.
                # Estaba fuera y sin proteger: el autoflush forzaba el INSERT
                # pendiente del fichero anterior, asi que el IntegrityError se
                # escapaba del bucle y se llevaba por delante los ficheros
                # restantes de la MISMA entrega. La idempotencia real la da el
                # re-chequeo de mas abajo, dentro del savepoint.
                with session.no_autoflush:
                    existing = session.exec(
                        select(Attachments).where(
                            Attachments.podio_file_id == file_id)
                    ).first()
                if existing:
                    print(f"⏭️ Archivo {file_id} ya existe, se omite.")
                    continue

                # Obtener metadata del archivo
                file_meta_resp = requests.get(
                    f"https://api.podio.com/file/{file_id}",
                    headers=headers,
                    timeout=TIMEOUT_PODIO
                )
                file_meta_resp.raise_for_status()
                file_meta = file_meta_resp.json()

                filename = file_meta.get("name", f"file_{file_id}")
                description = file_meta.get("description", "") or ""

                # Descargar archivo
                file_resp = requests.get(
                    f"https://api.podio.com/file/{file_id}/raw",
                    headers=headers,
                    stream=True,
                    timeout=TIMEOUT_PODIO
                )
                file_resp.raise_for_status()

                mimetype = file_resp.headers.get(
                    "Content-Type", "application/octet-stream"
                ).split(";")[0]
                file_bytes = file_resp.content

                # Subir a Cloudinary
                cloudinary_result = upload_to_cloudinary(
                    file_bytes=file_bytes,
                    filename=filename,
                    mimetype=mimetype,
                    folder=folder
                )

                # Guardar en DB — con la carrera contemplada.
                #
                # La comprobacion de `podio_file_id` de arriba se hace ANTES de
                # descargar de Podio y subir a Cloudinary, que tarda segundos.
                # Con varias entregas simultaneas del mismo evento las cinco
                # pasan esa comprobacion (ninguna ha insertado todavia), hacen
                # la subida, y `generate_custom_id` les da a todas el mismo
                # max+1. Cuatro estallan con:
                #   duplicate key value violates unique constraint
                #   "attachments_pkey" DETAIL: Key ("ID_Attachment")=(ATT62498)
                #
                # Medido en produccion el 20-ago-2026: el item 3345393757
                # (PAR6171) entro CINCO veces en 1,6 s y dejo 5 registros en
                # `podio_failed_syncs`, todos `file.change`.
                #
                # Dos defensas, en este orden:
                #  1. Re-comprobar `podio_file_id` justo antes de insertar. La
                #     ventana pasa de segundos a microsegundos.
                #  2. Reintentar con un ID nuevo si aun asi choca la PK. Si lo
                #     que choca es el fichero, es que otra entrega gano: no es
                #     un error, es idempotencia.
                from sqlalchemy.exc import IntegrityError

                ya_esta = session.exec(
                    select(Attachments).where(
                        Attachments.podio_file_id == file_id)
                ).first()
                if ya_esta:
                    print(f"⏭️ Archivo {file_id} lo guardo otra entrega, se omite.")
                    continue

                guardado = False
                for intento in range(1, 6):
                    new_id = generate_custom_id(
                        session, Attachments, "ID_Attachment", "ATT")
                    attachment = Attachments(
                        ID_Attachment=new_id,
                        Document_name=filename,
                        Attachment_descr=description,
                        Link=cloudinary_result["secure_url"],
                        Document_type=cloudinary_result["format"].lower(
                        ) or mimetype,
                        cloudinary_public_id=cloudinary_result["public_id"],
                        cloudinary_resource_type=cloudinary_result["resource_type"],
                        podio_file_id=file_id,
                        **{_fk_field: _fk_value}
                    )
                    try:
                        # SAVEPOINT: si choca, no se lleva por delante la
                        # transaccion del webhook entero (que es lo que producia
                        # el "This Session's transaction has been rolled back").
                        with session.begin_nested():
                            session.add(attachment)
                        guardado = True
                        break
                    except IntegrityError as choque:
                        if "podio_file_id" in str(choque.orig):
                            print(f"⏭️ Archivo {file_id} guardado en paralelo, se omite.")
                            break
                        print(f"↻ {new_id} ocupado (intento {intento}), reintentando")

                if guardado:
                    print(f"✅ {filename} → {_fk_field}: {_fk_value}")
                elif intento == 5:
                    # Antes se perdia con un print y nadie se enteraba.
                    logger.error(
                        "No se pudo asignar ID para el adjunto %s tras 5 intentos",
                        file_id)
                    record_failed_attachment(
                        item_id=item_id, file_id=file_id, app_type=app_type,
                        action_type="file_created", fk_field=_fk_field,
                        fk_value=_fk_value, filename=filename,
                        cloudinary_result=cloudinary_result,
                        error="No se pudo asignar ID_Attachment tras 5 intentos")

            except Exception as e:
                # Antes: print + continue. El fichero desaparecia sin dejar
                # rastro, el webhook respondia 200 y Podio NUNCA reenvia.
                logger.exception(
                    "Fallo procesando el adjunto %s (file_created)", file_id)
                record_failed_attachment(
                    item_id=item_id, file_id=file_id, app_type=app_type,
                    action_type="file_created", fk_field=_fk_field, fk_value=_fk_value,
                    filename=filename, cloudinary_result=cloudinary_result,
                    error=e)
                continue

    # ── FILE DELETED ──────────────────────────────────────────────
    elif action_type == "file_deleted":
        for file_id in file_id_list:
            # Reinicio por iteracion: sin esto el fallo del fichero N
            # registraria los datos del N-1.
            cloudinary_result = None
            filename = None
            obj = None

            try:
                obj = session.exec(
                    select(Attachments).where(
                        Attachments.podio_file_id == file_id)
                ).first()

                if not obj:
                    print(f"⚠️ Archivo {file_id} no existe en DB, se omite.")
                    continue

                # ----------- 🔴 ELIMINAR DE CLOUDINARY
                if obj.Link:
                    try:
                        parts = obj.Link.split("/upload/")
                        public_id = parts[1].split("/", 1)[1].rsplit(".", 1)[0]
                        resource_type = get_resource_type(
                            obj.Document_type or "")
                        delete_from_cloudinary(public_id, resource_type)
                        print(
                            f"☁️ Eliminado de Cloudinary | public_id={public_id}")
                    except Exception as e:
                        print(f"⚠️ Error eliminando de Cloudinary: {e}")

                # ----------- 🔴 ELIMINAR DE DB
                delete_with_retry(session, obj)
                print(f"🗑️ Attachment eliminado | podio_file_id={file_id}")

            except Exception as e:
                logger.exception(
                    "Fallo procesando el adjunto %s (file_deleted)", file_id)
                record_failed_attachment(
                    item_id=item_id, file_id=file_id, app_type=app_type,
                    action_type="file_deleted", fk_field=_fk_field, fk_value=_fk_value,
                    filename=filename, cloudinary_result=cloudinary_result,
                    error=e)
                continue

    # ── FILE REPLACED ─────────────────────────────────────────────
    elif action_type == "file_replaced":
        for file_id in file_id_list:
            cloudinary_result = None
            filename = None

            try:
                existing = session.exec(
                    select(Attachments).where(
                        Attachments.podio_file_id == file_id)
                ).first()
                if existing:
                    print(f"⏭️ Archivo {file_id} ya existe, se omite.")
                    continue

                # Tratar como file_created con el nuevo file_id
                process_file_change_event(
                    session=session,
                    data={
                        "action_type": "file_created",
                        "file_ids":    file_id,
                        "item_id":     item_id
                    },
                    app_type=app_type,
                    year=year,
                    id_jobs=id_jobs,
                    fk_field=fk_field,
                    fk_value=fk_value
                )

            except Exception as e:
                logger.exception(
                    "Fallo procesando el adjunto %s (file_replaced)", file_id)
                record_failed_attachment(
                    item_id=item_id, file_id=file_id, app_type=app_type,
                    action_type="file_replaced", fk_field=_fk_field, fk_value=_fk_value,
                    filename=filename, cloudinary_result=cloudinary_result,
                    error=e)
                continue

    else:
        print(f"⚠️ action_type no manejado: {action_type}")


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

        # Igual que en file_created: el registro del fallo lo necesita.
        cloudinary_result = None

        try:
            # Descargar de Podio
            response = requests.get(
                f"https://api.podio.com/file/{file_id}/raw",
                headers=headers,
                stream=True,
                timeout=TIMEOUT_PODIO
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
                cloudinary_public_id=cloudinary_result["public_id"],
                cloudinary_resource_type=cloudinary_result["resource_type"],
                podio_file_id=file_id,
                **{fk_field: fk_value}
            )

            # SAVEPOINT, igual que en file_created. Este `add` iba desnudo:
            # si el ID chocaba (mismo max+1 de generate_custom_id), la
            # excepcion no saltaba aqui sino en el flush/commit de mas
            # arriba en la pila, y se llevaba por delante los `add` de
            # TODOS los ficheros anteriores del mismo lote.
            with session.begin_nested():
                session.add(attachment)
            print(f"✅ {filename} → {fk_field}: {fk_value}")

        except Exception as e:
            # Mismo agujero que file_created, y este corre en el alta y la
            # actualizacion de items, no solo en file.change. Ademas aqui NO
            # hay savepoint ninguno.
            #
            # OJO con el identificador: esta funcion NO recibe el item_id de
            # Podio, solo `id_jobs` (p.ej. "QID51894") o `entity_id` (id local
            # de la otra app). Se guarda el que haya y ademas los dos van al
            # payload, para que quien recupere sepa cual esta leyendo. No es
            # un podio_item_id: no mezclarlos al reconciliar.
            logger.exception(
                "Fallo procesando el adjunto %s (item_attachments)", file_id)
            record_failed_attachment(
                item_id=id_jobs or entity_id, file_id=file_id,
                app_type=app_type, action_type="item_attachments",
                fk_field=fk_field, fk_value=fk_value,
                filename=filename, cloudinary_result=cloudinary_result,
                error=e)
            continue
