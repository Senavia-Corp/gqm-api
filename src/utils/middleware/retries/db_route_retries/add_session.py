from sqlalchemy.exc import IntegrityError

from src.utils.middleware.logs.logs import logger
import time

def save_with_retry(session, obj, max_retries=3, delay=1):
    """
    Agrega un objeto a la DB con retry. Hace rollback explícito en cada fallo
    para evitar PendingRollbackError en reintentos subsecuentes.

    IntegrityError NO se reintenta: una PK o UNIQUE duplicada es determinista,
    el segundo intento falla igual que el primero. Reintentarla costaba los 3
    intentos completos con sus esperas (~4,4 s medidos) dentro de una entrega
    de webhook, y el margen de Podio antes de dar la entrega por fallida es de
    unos 15 s. Se propaga en el primer intento para que el llamador la mande a
    la dead-letter y conteste rápido.
    """
    for attempt in range(1, max_retries + 1):
        try:
            session.add(obj)
            session.commit()
            session.refresh(obj)
            return obj
        except IntegrityError as e:
            session.rollback()
            logger.error(f"[save_with_retry] IntegrityError, sin reintento: {e}")
            raise
        except Exception as e:
            session.rollback()
            logger.error(f"[save_with_retry] Error en intento {attempt}/{max_retries}: {e}")
            if attempt == max_retries:
                logger.critical("[save_with_retry] Falló permanentemente.")
                raise
            time.sleep(delay)
