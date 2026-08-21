from src.models.PodioFailedSyncModel import PodioFailedSync
from src.utils.error_sanitizer import sanitize_error
from src.utils.middleware.logs.logs import logger


def record_failed_sync(session, *, item_id, hook_type, payload, error) -> None:
    """Registra un fallo de sincronización para reconciliar después.

    Rollback defensivo SIEMPRE: los llamadores están en un `except` y la
    sesión puede venir abortada; sin esto el add+commit fallaría en silencio.
    El error se persiste saneado (sin SQL/parámetros) — el detalle completo
    ya quedó en logs del llamador.
    """
    try:
        session.rollback()
        session.add(PodioFailedSync(
            item_id=str(item_id) if item_id else None,
            hook_type=hook_type,
            payload=payload,
            error_message=sanitize_error(error),
        ))
        session.commit()
    except Exception:
        logger.exception("No se pudo registrar PodioFailedSync (%s)", hook_type)


def record_failed_attachment(*, item_id, file_id, app_type, action_type,
                             fk_field=None, fk_value=None, filename=None,
                             cloudinary_result=None, error) -> None:
    """Registra un adjunto perdido, en SESION PROPIA.

    Por que sesion propia y no la del webhook: `record_failed_sync` hace
    `session.rollback()` como PRIMERA instruccion (arriba, linea 15). Llamarlo
    con la sesion compartida desde dentro del bucle de ficheros descartaria
    TODOS los adjuntos ya encolados de esa entrega mas el update del Job que la
    precedio — `file_created` no commitea por fichero, hace `session.add()` en
    bucle y un solo commit al final. Un SAVEPOINT tampoco vale: si la sesion ya
    viene abortada por un IntegrityError, `begin_nested()` sobre una
    transaccion abortada falla igual. Mismo patron que `_fallo_receptor_others`
    (`src/routes/Webhook_bp.py:122`).

    Por que los datos de recuperacion van al PAYLOAD y no al error_message:
    hoy el rastro que permitio identificar los 12 ficheros perdidos de agosto
    era un ACCIDENTE — el volcado crudo de SQLAlchemy en `str(e)`, que arrastra
    `[SQL: ...] [parameters: {...}]`. Eso es una fuga: el dia que falle un
    INSERT sobre una tabla con una columna de token, ese token acaba literal en
    esta tabla y sale por `GET /webhook/podio/failed_syncs`. Aqui el
    `error_message` va saneado y lo recuperable va en `payload`, que ademas es
    JSON consultable en vez de una regex sobre un log.

    `cloudinary_public_id` / `link` presentes significan "subido a Cloudinary
    pero NO persistido": se recupera sin volver a bajar de Podio. Ausentes,
    nunca llego a subirse. Esa distincion es la que abarata el rescate.
    """
    from src.database.db_sqlmodel import get_session

    cl = cloudinary_result or {}
    try:
        with get_session() as s:
            record_failed_sync(
                s,
                item_id=item_id,
                hook_type=f"podio.attachment.{action_type}",
                payload={
                    "file_id": str(file_id) if file_id is not None else None,
                    "app_type": app_type,
                    "action_type": action_type,
                    "fk_field": fk_field,
                    "fk_value": fk_value,
                    "filename": filename,
                    "cloudinary_public_id": cl.get("public_id"),
                    "cloudinary_resource_type": cl.get("resource_type"),
                    "link": cl.get("secure_url"),
                },
                error=error,
            )
    except Exception:
        # Ultima red: que registrar el fallo no pueda tumbar la entrega.
        logger.exception(
            "No se pudo registrar el adjunto fallido (file_id=%s, item=%s)",
            file_id, item_id)
