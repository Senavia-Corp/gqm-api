from src.utils.middleware.logs.logs import logger
import time

def save_with_retry(session, obj, max_retries=3, delay=1):
    """
    Agrega un objeto a la DB con retry. Hace rollback explícito en cada fallo
    para evitar PendingRollbackError en reintentos subsecuentes.
    """
    for attempt in range(1, max_retries + 1):
        try:
            session.add(obj)
            session.commit()
            session.refresh(obj)
            return obj
        except Exception as e:
            session.rollback()
            logger.error(f"[save_with_retry] Error en intento {attempt}/{max_retries}: {e}")
            if attempt == max_retries:
                logger.critical("[save_with_retry] Falló permanentemente.")
                raise
            time.sleep(delay)
