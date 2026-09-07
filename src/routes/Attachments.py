# ======================================== Código para la Base de Datos en Postgresql =================================
import requests
from flask import Blueprint, jsonify, request
from sqlmodel import select
from sqlalchemy.orm import joinedload

from ..database.db_sqlmodel import get_session
from ..models.AttachmentsModel import Attachments, AttachmentsUpdate
from ..utils.id_generator import generate_custom_id
from ..utils.relationships import add_relationships
from ..utils.middleware.retries.db_route_retries.add_session import save_with_retry
from ..utils.middleware.retries.db_route_retries.delete_session import delete_with_retry
from ..utils.middleware.exceptions_handler import handle_exceptions, AppException
from ..utils.middleware.logs.logs import logger
from ..utils.middleware.auth.routes_protection import (
    require_permission, portal_scope, scope_jobs_statement,
    job_belongs_to_portal_user, portal_owns_subcontractor)
from ..utils.policy_evaluator import PolicyEvaluator
from ..utils.portal_redaction import llamante_es_portal
from flask import g
from src.podio.podio_auth import get_podio_headers
from src.cloudinary.service import (
    upload_to_cloudinary, delete_from_cloudinary, get_resource_type,
    identidad_cloudinary)

# Blueprint de Attachments:
attachments_bp = Blueprint("attachments_blueprint",
                           __name__, url_prefix="/attachments")

# -------------------RUTAS CRUD-------------------#


def _alcance_portal(statement):
    """P-03: acota un `select(Attachments)` a lo que el llamante de portal posee.

    El staff no pasa por aqui: `portal_scope()` le devuelve (None, None) y el
    statement sale intacto.

    Decision ratificada (ambiguedad 9) — visibilidad mutua dentro del equipo:
    el subcontratista alcanza los adjuntos de SUS jobs, los suyos propios y los
    de SUS tecnicos; el tecnico, los de los jobs que tiene asignados y los
    suyos. Nada de otro sub.

    El alcance de jobs se delega en `scope_jobs_statement` — la misma primitiva
    sobre la que se apoya `job_belongs_to_portal_user` — para no reescribir aqui
    la logica de las tablas puente y que el listado y la lectura por id no se
    desincronicen.
    """
    rol, uid = portal_scope()
    if rol is None:
        return statement

    from sqlalchemy import or_ as sa_or

    from ..models.CertificateModel import Certificate
    from ..models.JobModel import Job
    from ..models.TechnicianModel import Technician

    # Subconsulta de ids: el filtro va EN EL STATEMENT, antes de materializar y
    # de paginar. Filtrar la lista ya traida dejaria la fuga en la primera
    # pagina y el coste de leer el corpus entero en cada peticion.
    jobs_propios = scope_jobs_statement(select(Job.ID_Jobs))
    condiciones = [Attachments.ID_Jobs.in_(jobs_propios)]

    if rol == "technician":
        condiciones.append(Attachments.ID_Technician == uid)
    else:
        condiciones.append(Attachments.ID_Subcontractor == uid)
        condiciones.append(Attachments.ID_Technician.in_(
            select(Technician.ID_Technician).where(
                Technician.ID_Subcontractor == uid)))
        # Faltaba la rama de certificados: `upload_attachment` le PERMITE al
        # sub colgar un adjunto de su certificado (entity_type == "certificate",
        # con `portal_owns_subcontractor` sobre el dueño), y este alcance no la
        # contemplaba — asi que subia el fichero y luego no podia releerlo ni
        # por lista ni por id. Se cierra el circulo con la misma regla de
        # pertenencia que usa la subida.
        condiciones.append(Attachments.ID_Certificate.in_(
            select(Certificate.ID_Certificate).where(
                Certificate.ID_Subcontractor == uid)))

    return statement.where(sa_or(*condiciones))


def _portal_posee_adjunto(session, att) -> bool:
    """¿El adjunto esta dentro del alcance del portal actual? Staff siempre.

    Reutiliza `_alcance_portal` para que la comprobacion POR ID diga
    exactamente lo mismo que el listado. Una divergencia entre el listado y la
    lectura o escritura por id es justo el hueco por el que se cuelan los IDOR
    — es el mismo razonamiento que `scope_tasks_statement` y
    `task_belongs_to_portal_user` (routes_protection.py:379-383).
    """
    rol, _ = portal_scope()
    if rol is None:
        return True
    stmt = _alcance_portal(select(Attachments).where(
        Attachments.ID_Attachment == att.ID_Attachment))
    return session.exec(stmt).first() is not None


def _portal_ve_adjunto(user_policies, att) -> bool:
    """Gate de carpeta para roles de portal, sin el atajo global.

    `attachment:read` global cortocircuitaba el filtro por carpeta, y AMBAS
    politicas de portal lo conceden (seed_rbac.py:89 y :102) — por eso el
    bloque de filtrado no se ejecutaba nunca y el sub A recibia
    ATT60001..ATT60004, los adjuntos del job de sub_B incluidos.

    Toma la FILA y no solo el nivel, porque la regla depende de la entidad de
    la que cuelga el adjunto:

    * **Cuelga de un JOB** — decision del cliente: de un job, el portal solo ve
      la carpeta «technicians». Antes, cualquier valor fuera de
      {members, technicians} caia en el `return True` del final y decidia solo
      la pertenencia; como la sincronizacion desde Podio NUNCA escribe
      `access_level` (podio_webhook_core.py:740-750) y el logbook escribe
      `access_level="logbook"` CON `ID_Jobs` (ChatMessage.py:212-221), eso
      significaba que el sub recibia, de sus propios jobs, todo lo sincronizado
      y todo el logbook. Es la simetrica de la regla de subida: lo unico que un
      rol de portal puede escribir en un job es `technicians`, y lo unico que
      puede leer es `technicians`.

    * **No cuelga de un job** (su propia ficha, sus tecnicos, sus
      certificados) — se conserva la regla anterior tal cual. `_alcance_portal`
      ya probo que la fila es suya, y ahi no hay vocabulario de carpetas:
      mapear un nivel desconocido a `attachment:read_<lo_que_sea>` inventaria
      un permiso que no tiene NADIE y le negaria al sub sus propios
      documentos.
    """
    carpeta = (getattr(att, "access_level", None) or "").strip().lower()

    if getattr(att, "ID_Jobs", None) is not None:
        return carpeta == "technicians" and PolicyEvaluator.evaluate(
            user_policies, "attachment:read_technicians")

    if carpeta in ("members", "technicians"):
        return PolicyEvaluator.evaluate(
            user_policies, f"attachment:read_{carpeta}")
    return True


# --------------------RUTAS GET-------------------#
# Ruta para conseguir la lista de todos los attachments
@attachments_bp.get("/")
@require_permission(["attachment:read", "attachment:read_members", "attachment:read_technicians"])
@handle_exceptions()
def list_attachments():
    # Filtro opcional: ?access_level=members | technicians
    access_level = request.args.get("access_level", "").strip().lower() or None

    with get_session() as session:
        statement = (
            select(Attachments)
            .options(
                joinedload(Attachments.job),
                joinedload(Attachments.subcontractor),
                joinedload(Attachments.technician)
            )
        )

        if access_level:
            statement = statement.where(
                Attachments.access_level == access_level)

        # P-03 (S1): pertenencia en el statement, antes de materializar. Para el
        # staff es un no-op.
        statement = _alcance_portal(statement)

        results = session.exec(statement).unique().all()

        # Filter by folder-level read permission when the user lacks global read
        user_policies = getattr(g, "user_policies", [])
        rol_portal, _ = portal_scope()
        if rol_portal is not None:
            # P-03: el atajo por `attachment:read` global NO aplica al portal.
            results = [att for att in results
                       if _portal_ve_adjunto(user_policies, att)]
        elif not PolicyEvaluator.evaluate(user_policies, "attachment:read"):
            can_read_members = PolicyEvaluator.evaluate(
                user_policies, "attachment:read_members")
            can_read_technicians = PolicyEvaluator.evaluate(
                user_policies, "attachment:read_technicians")
            results = [
                att for att in results
                if (att.access_level == "technicians" and can_read_technicians)
                or (att.access_level != "technicians" and can_read_members)
            ]

        if not results:
            # Esta ruta responde 404 con cuerpo de TEXTO cuando la lista sale
            # vacia. Para el staff es una rareza (solo con la tabla vacia); para
            # un rol de portal, con la pertenencia ya aplicada, pasa a ser el
            # estado NORMAL de un sub recien dado de alta y sin jobs — y un 404
            # ahi se lee como permiso roto, no como «no tienes ninguno».
            # Se devuelve la coleccion vacia con 200 solo para el portal: el
            # staff conserva el 404 historico que el panel ya consume.
            if rol_portal is not None:
                return [], 200
            return jsonify("No se han encontrado archivos adjuntos."), 404

        attachments_data = [
            add_relationships(att, ["job", "subcontractor", "technician"])
            for att in results
        ]

        return attachments_data, 200


# Ruta para conseguir un attachment por ID
@attachments_bp.get("/<id_attachment>")
@require_permission(["attachment:read", "attachment:read_members", "attachment:read_technicians"])
@handle_exceptions()
def get_attachment_by_id(id_attachment):

    with get_session() as session:
        statement = (
            select(Attachments)
            .options(
                joinedload(Attachments.job),
                joinedload(Attachments.subcontractor),
                joinedload(Attachments.technician)
            )
            .where(Attachments.ID_Attachment == id_attachment)
        )
        # P-03 (S1): la pertenencia se aplica EN EL STATEMENT, no despues. Asi
        # un adjunto ajeno queda indistinguible de uno inexistente y las dos
        # ramas caen en el mismo 404, que es la convencion de esta base de
        # codigo para roles de portal (Job.py:506-507, modismo de Tasks.py:170):
        # un 403 confirmaria la existencia y haria la ruta enumerable.
        # De paso cierra el oraculo que tenia esta ruta — 404 si no existe, 403
        # si existe y es ajeno — que juntos distinguian «no hay» de «hay y no es
        # tuyo». El staff pasa sin filtro.
        statement = _alcance_portal(statement)
        obj = session.exec(statement).unique().first()

        if not obj:
            raise AppException("Attachment no encontrado.",
                               "attachment_not_found", 404)

        # Check folder-specific read permission
        user_policies = getattr(g, "user_policies", [])
        rol_portal, _ = portal_scope()
        if rol_portal is not None:
            # P-03: el atajo por `attachment:read` global NO aplica al portal.
            # Aqui el 403 ya no es enumerable: solo se alcanza sobre un adjunto
            # que YA se ha comprobado que es suyo.
            if not _portal_ve_adjunto(user_policies, obj):
                return jsonify({"error": "Forbidden: You do not have permission to read this attachment"}), 403
        elif not PolicyEvaluator.evaluate(user_policies, "attachment:read"):
            folder = obj.access_level or "members"
            folder_action = f"attachment:read_{folder}"
            if not PolicyEvaluator.evaluate(user_policies, folder_action):
                return jsonify({"error": "Forbidden: You do not have permission to read this attachment"}), 403

        attachment_data = add_relationships(
            obj, ["job", "subcontractor", "technician"])

        return jsonify(attachment_data), 200


# --------------- RUTAS POST, PATCH AND DELETE----------#

# UPLOAD (Frontend → Backend)
# --> Flujo: Cloudinary → Podio → DB
@attachments_bp.post("/upload")
@require_permission(["attachment:create", "attachment:create_members", "attachment:create_technicians"])
@handle_exceptions()
def upload_attachment():
    """
    Recibe un archivo desde Next.js.
    Sube a Cloudinary, adjunta en Podio y guarda en DB.

    Form-data esperado:
        - file:         El archivo
        - entity_id:    ID interno en DB (ej: "PAR5147") — deriva entity_type y app_type
        - year:         Año del Job
        - description:  Descripción opcional
        - tag:          Tag opcional (default: "general")
        - access_level: Nivel de acceso/carpeta (ej: "members", "technicians"). Solo aplica para Jobs.
    """
    sync_podio = request.args.get("sync_podio", "false").lower() == "true"

    # ── 1. Validar archivo y campos ──────────────────────────────
    if "file" not in request.files:
        raise AppException("No se encontró el archivo.", "file_missing", 400)

    file = request.files["file"]
    entity_id = request.form.get("entity_id")
    year = request.form.get("year")
    description = request.form.get("description", "")
    tag = request.form.get("tag", "general")
    access_level = request.form.get("access_level", "").strip().lower()

    if not file.filename:
        raise AppException("El archivo no tiene nombre.", "file_no_name", 400)

    if not entity_id:
        raise AppException(
            "entity_id es requerido.",
            "missing_fields", 400
        )

    year = int(year) if year else None

    # ── 1b. Folder-specific create permission check ──────────────
    user_policies = getattr(g, "user_policies", [])
    if not PolicyEvaluator.evaluate(user_policies, "attachment:create"):
        folder_for_check = access_level if access_level in [
            "members", "technicians"] else "members"
        folder_action = f"attachment:create_{folder_for_check}"
        if not PolicyEvaluator.evaluate(user_policies, folder_action):
            return jsonify({"error": f"Forbidden: You do not have permission to upload to the {folder_for_check} folder"}), 403

    # ── 2. Derivar entity_type y app_type del entity_id ──────────
    JOB_PREFIXES = ["QID", "PTL", "PAR"]
    entity_id_upper = entity_id.upper()

    if any(entity_id_upper.startswith(p) for p in JOB_PREFIXES):
        entity_type = "job"
        app_type = next(
            p for p in JOB_PREFIXES if entity_id_upper.startswith(p))
    elif entity_id_upper.startswith("CLI"):
        entity_type = "client"
        app_type = "CLI"
    elif entity_id_upper.startswith("SUBC"):
        entity_type = "subcontractor"
        app_type = "SUBC"
    elif entity_id_upper.startswith("BLGDEP"):
        entity_type = "building_dept"
        app_type = "BLGDEP"
    elif entity_id_upper.startswith("CER"):
        entity_type = "certificate"
        app_type = "CER"
    else:
        raise AppException(
            f"No se pudo determinar el tipo de entidad para: {entity_id}",
            "unknown_entity_type", 400
        )

    # ── 2bis. Pertenencia del destino ────────────────────────────
    #
    # El `entity_id` viene del formulario y el tipo se deduce de su PREFIJO: no
    # se comprobaba en ningun momento que el destino fuera del llamante. Un
    # subcontratista podia colgar ficheros en el job de otro, o en su ficha.
    #
    # Va ANTES de leer el fichero y de subirlo a Cloudinary: si se comprobara
    # despues, el fichero ya estaria en el almacenamiento externo aunque la fila
    # no llegara a crearse.
    #
    # 404 y no 403, como el resto de rutas de portal: un 403 confirmaria que ese
    # job o esa ficha existen.
    if llamante_es_portal():
        with get_session() as sesion_guarda:
            if entity_type == "job":
                permitido = job_belongs_to_portal_user(sesion_guarda, entity_id)
            elif entity_type == "subcontractor":
                permitido = portal_owns_subcontractor(entity_id)
            elif entity_type == "certificate":
                from ..models.CertificateModel import Certificate
                cert = sesion_guarda.get(Certificate, entity_id)
                permitido = bool(cert) and portal_owns_subcontractor(
                    cert.ID_Subcontractor)
            else:
                # `client` y `building_dept` no son destinos de portal.
                permitido = False
        if not permitido:
            raise AppException("Entity not found", "not_found", 404)

        # ── 2ter. La carpeta, cuando el destino es un JOB ─────────
        #
        # El gate de carpeta de arriba (:262-269) se cortocircuita con
        # `attachment:create` GLOBAL, y ambas politicas de portal lo conceden
        # (seed_rbac.py:90) — esta ahi para que el sub suba sus PROPIOS
        # certificados, asi que quitarselo le retiraria una capacidad que usa.
        # La politica no se toca: la regla es de ruta y se deriva de la
        # ENTIDAD destino. Decision del cliente: de un job, el portal solo
        # trabaja la carpeta «technicians».
        #
        # 403 y no 404: la pertenencia ya quedo probada tres lineas arriba, asi
        # que no hay existencia que ocultar, y responder «no existe» sobre un
        # job que el usuario esta mirando seria mentirle. Tampoco 400: la
        # peticion no es invalida —byte a byte, la misma que un admin envia con
        # exito—, lo que cambia es QUIEN pregunta, y eso es un 403. Es ademas
        # el codigo que ya usa el gate de carpeta vecino (:269).
        #
        # `access_level` viene ya normalizado (`.strip().lower()`, :249) y es
        # "" cuando no se envia, asi que el caso sin etiqueta —el que produce
        # la sincronizacion de Podio— cae por la misma comparacion. NO se
        # traduce "" a "technicians": eso reescribiria la intencion en
        # silencio y taparia un fallo del panel en vez de enseñarlo.
        if entity_type == "job" and access_level != "technicians":
            raise AppException(
                "Forbidden: desde el portal solo se puede subir a la carpeta "
                "«technicians» de un job.",
                "forbidden_folder", 403)

    # ── 3. Leer archivo ──────────────────────────────────────────
    filename = file.filename
    file_bytes = file.read()
    mimetype = file.mimetype or "application/octet-stream"

    # ── 4. Subir a Cloudinary ────────────────────────────────────
    # Folder base p.ej: Jobs/PAR/PAR5147
    if entity_type == "job":
        folder = f"Jobs/{app_type}/{entity_id}"
        if access_level in ["members", "technicians"]:
            folder = f"{folder}/{access_level}"
        elif access_level:
            folder = f"{folder}/{access_level}"
    elif entity_type == "certificate":
        # Buscar el subcontratista dueño del certificado para anidar la carpeta
        from ..models.CertificateModel import Certificate as CertificateModel
        with get_session() as session_lookup:
            cert_obj = session_lookup.exec(
                select(CertificateModel).where(CertificateModel.ID_Certificate == entity_id)
            ).first()
        if cert_obj and cert_obj.ID_Subcontractor:
            folder = f"SUBC/{cert_obj.ID_Subcontractor}/CER/{entity_id}"
        else:
            folder = f"CER/{entity_id}"
    else:
        folder = f"{app_type}/{entity_id}"

    tags = f"{tag},{entity_id}"

    cloudinary_result = upload_to_cloudinary(
        file_bytes=file_bytes,
        filename=filename,
        mimetype=mimetype,
        folder=folder,
        tags=tags
    )

    logger.info("☁️ Archivo subido a Cloudinary | %s → %s",
                filename, cloudinary_result["secure_url"])

    # ── 5. Buscar podio_item_id internamente y adjuntar en Podio ─
    podio_file_id = None

    if sync_podio:
        from src.models.JobModel import Job

        with get_session() as session_lookup:
            if entity_type == "job":
                entity_obj = session_lookup.exec(
                    select(Job).where(Job.ID_Jobs == entity_id)
                ).first()
            # Agrega más entidades aquí cuando las necesites

        if not entity_obj:
            raise AppException(
                f"Entidad {entity_id} no encontrada en DB.",
                "entity_not_found", 404
            )

        if not entity_obj.podio_item_id:
            raise AppException(
                f"{entity_id} no tiene podio_item_id registrado.",
                "missing_podio_item_id", 400
            )

        podio_item_id = entity_obj.podio_item_id
        headers = get_podio_headers(app_type, year=year)

        # ----------- 🟢 SUBIR ARCHIVO A PODIO
        upload_resp = requests.post(
            "https://api.podio.com/file/",
            headers={"Authorization": headers["Authorization"]},
            files={"source": (filename, file_bytes, mimetype)},
            data={"filename": filename}
        )
        upload_resp.raise_for_status()
        podio_file_id = str(upload_resp.json().get("file_id"))

        # ----------- 🟢 ADJUNTAR AL ITEM EN PODIO
        attach_resp = requests.post(
            f"https://api.podio.com/file/{podio_file_id}/attach",
            headers=headers,
            json={"ref_type": "item", "ref_id": int(podio_item_id)}
        )
        attach_resp.raise_for_status()

        logger.info("📎 Archivo adjuntado en Podio | file_id=%s → item_id=%s",
                    podio_file_id, podio_item_id)

    # ── 6. Guardar en DB ─────────────────────────────────────────
    with get_session() as session:

        # Evitar duplicados por podio_file_id
        if podio_file_id:
            existing = session.exec(
                select(Attachments).where(
                    Attachments.podio_file_id == podio_file_id)
            ).first()
            if existing:
                return jsonify(existing.model_dump()), 200

        new_id = generate_custom_id(
            session, Attachments, "ID_Attachment", "ATT")

        # FK dinámica según entity_type
        fk_kwargs = {}
        if entity_type == "job":
            fk_kwargs["ID_Jobs"] = entity_id
        elif entity_type == "subcontractor":
            fk_kwargs["ID_Subcontractor"] = entity_id
        elif entity_type == "client":
            fk_kwargs["ID_Client"] = entity_id
        elif entity_type == "building_dept":
            fk_kwargs["ID_BldgDept"] = entity_id
        elif entity_type == "certificate":
            fk_kwargs["ID_Certificate"] = entity_id

        # ----------- 💾 GUARDAR EN DB
        attachment = Attachments(
            ID_Attachment=new_id,
            Document_name=cloudinary_result["original_name"],
            Attachment_descr=description,
            Link=cloudinary_result["secure_url"],
            Document_type=cloudinary_result["format"].lower() or mimetype,
            cloudinary_public_id=cloudinary_result["public_id"],
            cloudinary_resource_type=cloudinary_result["resource_type"],
            podio_file_id=podio_file_id,
            access_level=access_level or None,
            **fk_kwargs
        )

        save_with_retry(session, attachment)

        logger.info("✅ Attachment creado | attachment_id=%s | entity_id=%s",
                    new_id, entity_id)

        return jsonify({
            "success":         True,
            "attachment":      attachment.model_dump(),
            "cloudinary_url":  cloudinary_result["secure_url"]
        }), 201


# Ruta para actualizar la metadata en DB
@attachments_bp.patch("/<id_attachment>")
@require_permission(["attachment:update", "attachment:update_members", "attachment:update_technicians"])
@handle_exceptions()
def update_attachment(id_attachment):
    data = request.get_json()

    with get_session() as session:
        obj = session.get(Attachments, id_attachment)
        if not obj:
            raise AppException("Attachment no encontrado.",
                               "attachment_not_found", 404)

        # P-03, segunda linea: estas dos rutas hacian `session.get` y decidian
        # solo por permiso de carpeta. Hoy las frena unicamente el decorador
        # —ninguna politica de portal concede attachment:update/delete—, o sea
        # que estan a UN cambio de politica de ser un IDOR con efectos de
        # escritura. La pertenencia no deberia depender de eso.
        if not _portal_posee_adjunto(session, obj):
            raise AppException("Attachment no encontrado.",
                               "attachment_not_found", 404)

        # Check folder-specific update permission
        user_policies = getattr(g, "user_policies", [])
        if not PolicyEvaluator.evaluate(user_policies, "attachment:update"):
            folder = obj.access_level or "members"
            folder_action = f"attachment:update_{folder}"
            if not PolicyEvaluator.evaluate(user_policies, folder_action):
                return jsonify({"error": "Forbidden: You do not have permission to edit this attachment"}), 403

        update_att = AttachmentsUpdate.model_validate(data)
        update_data_dict = update_att.model_dump(exclude_unset=True)

        # ----------- 🔄 ACTUALIZAR EN DB
        for key, value in update_data_dict.items():
            setattr(obj, key, value)

        save_with_retry(session, obj)

        logger.info("🔄 Attachment actualizado | attachment_id=%s",
                    id_attachment)

        return jsonify(obj.model_dump()), 200


# Ruta para eliminar un attachment
# --> Flujo: Cloudinary → Podio → DB
@attachments_bp.delete("/<id_attachment>")
@require_permission(["attachment:delete", "attachment:delete_members", "attachment:delete_technicians"])
@handle_exceptions()
def delete_attachment(id_attachment):

    sync_podio = request.args.get("sync_podio", "false").lower() == "true"
    app_type = request.args.get("app_type", "").upper()
    year = request.args.get("year")
    year = int(year) if year else None

    with get_session() as session:
        obj = session.get(Attachments, id_attachment)
        if not obj:
            raise AppException("Attachment no encontrado.",
                               "attachment_not_found", 404)

        # P-03, segunda linea: estas dos rutas hacian `session.get` y decidian
        # solo por permiso de carpeta. Hoy las frena unicamente el decorador
        # —ninguna politica de portal concede attachment:update/delete—, o sea
        # que estan a UN cambio de politica de ser un IDOR con efectos de
        # escritura. La pertenencia no deberia depender de eso.
        if not _portal_posee_adjunto(session, obj):
            raise AppException("Attachment no encontrado.",
                               "attachment_not_found", 404)

        # Check folder-specific delete permission
        user_policies = getattr(g, "user_policies", [])
        if not PolicyEvaluator.evaluate(user_policies, "attachment:delete"):
            folder = obj.access_level or "members"
            folder_action = f"attachment:delete_{folder}"
            if not PolicyEvaluator.evaluate(user_policies, folder_action):
                return jsonify({"error": "Forbidden: You do not have permission to delete this attachment"}), 403

        # ORDEN: Podio -> Cloudinary -> BD.
        #
        # Estaba al reves (Cloudinary -> Podio -> BD) y dejaba el peor estado
        # posible: si el borrado en Podio fallaba, el 502 abortaba antes de
        # tocar la BD... pero el binario de Cloudinary YA no existia. La fila
        # sobrevivia con su `Link` apuntando a un fichero muerto, y el usuario
        # veia el adjunto en el panel hasta que hacia clic.
        #
        # Podio primero porque es el unico paso reversible por el usuario y la
        # fuente de verdad: si falla, no se ha destruido nada y se puede
        # reintentar entero.
        # ----------- 🔴 BORRAR EN PODIO (SI APLICA)
        if sync_podio and obj.podio_file_id:
            try:
                if not app_type:
                    raise AppException(
                        "app_type es requerido cuando sync_podio=true.",
                        "missing_app_type", 400
                    )

                headers = get_podio_headers(app_type, year=year)

                delete_resp = requests.delete(
                    f"https://api.podio.com/file/{obj.podio_file_id}",
                    headers=headers
                )
                delete_resp.raise_for_status()

                logger.info("🗑️ Archivo eliminado de Podio | podio_file_id=%s",
                            obj.podio_file_id)

            except AppException:
                raise
            except Exception:
                logger.exception(
                    "❌ Error eliminando archivo de Podio | podio_file_id=%s",
                    obj.podio_file_id
                )
                raise AppException(
                    "Error al eliminar el archivo de Podio.",
                    "podio_delete_failed", 502
                )

        # ----------- 🔴 BORRAR EN CLOUDINARY
        if obj.Link:
            try:
                # REG-058: usar la identidad persistida al subir. Lo que hacia
                # la rama legacy estaba mal por dos sitios y afecta a 2.288 de
                # las 2.493 filas: no hacia `unquote()` (las URLs vienen
                # percent-codificadas: %28 por parentesis, y son 13 de las 205
                # comprobables) y le pasaba `Document_type` a
                # `get_resource_type`, que espera un MIMETYPE — para las
                # imagenes ahi hay una EXTENSION ('jpg', 'png', 'webp'), que no
                # es clave del mapa y caia al default 'raw'.
                #
                # `identidad_cloudinary` centraliza las dos cosas. Validado
                # contra las 205 filas con identidad persistida: resource_type
                # 205/205, public_id 192/205 identico y las 13 que difieren son
                # exactamente las de URL codificada.
                public_id, resource_type = identidad_cloudinary(obj)
                deleted = delete_from_cloudinary(public_id, resource_type)

                if deleted:
                    logger.info(
                        "☁️ Archivo eliminado de Cloudinary | public_id=%s", public_id)
                else:
                    logger.warning(
                        "⚠️ No se pudo eliminar de Cloudinary | public_id=%s", public_id)

            except Exception as e:
                # No bloqueamos el delete si falla Cloudinary
                logger.warning(
                    "⚠️ Error al eliminar de Cloudinary | %s", str(e))

        # ----------- 🔴 BORRAR EN DB
        delete_with_retry(session, obj)

        logger.info("🗑️ Attachment eliminado | attachment_id=%s",
                    id_attachment)

        return jsonify({
            "message": f"Attachment {id_attachment} eliminado correctamente."
        }), 200
