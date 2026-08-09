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
