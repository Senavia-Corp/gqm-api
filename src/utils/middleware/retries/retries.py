
import time
import functools
from src.utils.middleware.logs.logs import logger

# Códigos por los que merece la pena reintentar una LECTURA idempotente.
# Cualquier otro 4xx (403 de token malo, 404 de app inexistente) propaga ya:
# reintentarlo no lo va a arreglar y gasta presupuesto de reloj.
ESTADOS_REINTENTABLES = {429, 500, 502, 503, 504}


def _espera_sugerida(exc):
    """Retry-After de la respuesta, en segundos. None si no viene o no es un número."""
    resp = getattr(exc, "response", None)
    if resp is None:
        return None
    try:
        return max(0.0, float(resp.headers.get("Retry-After")))
    except (AttributeError, TypeError, ValueError):
        return None


def retry_api_lectura(max_retries=3, backoff=0.5, tope=4.0):
    """Reintento para lecturas idempotentes contra Podio (GET, y el POST de
    `/filter/`, que no muta nada).

    Se separa de `retry_api` a propósito: aquel atrapa `Exception` y duerme 2 s
    y luego 4 s ante *cualquier* fallo, así que un 403 cuesta 6 s. El paginador
    corre con un presupuesto de reloj, y ahí 6 s por una página que nunca va a
    funcionar es la diferencia entre terminar una app y no terminarla.

    NO usar para escrituras: reintentar un `create_item` duplica items en Podio.
    """
    import requests

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = backoff

            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)

                except requests.exceptions.HTTPError as e:
                    estado = getattr(e.response, "status_code", None)
                    if estado not in ESTADOS_REINTENTABLES or attempt == max_retries:
                        raise
                    espera = _espera_sugerida(e)
                    espera = delay if espera is None else espera

                except (requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout) as e:
                    if attempt == max_retries:
                        raise
                    espera = delay

                logger.info(
                    f"[retry_api_lectura] intento {attempt}/{max_retries} falló; "
                    f"reintentando en {espera:.1f}s")
                time.sleep(espera)
                delay = min(delay * 2, tope)

        return wrapper

    return decorator


def _es_permanente(e) -> bool:
    """¿Reintentar esto tiene alguna posibilidad de salir distinto?

    La guarda de entorno (`EscrituraFueraDeEntorno`) no es un fallo transitorio:
    el item pertenece a la app que pertenece, y va a seguir perteneciendo dentro
    de dos segundos. Reintentarlo tres veces con backoff sólo gasta tiempo — en
    las pruebas se nota mucho, y en produccion multiplica por tres la latencia
    de cada escritura bloqueada.
    """
    from src.podio.services.podio_base_services import EscrituraFueraDeEntorno

    return isinstance(e, EscrituraFueraDeEntorno)


def retry_api(max_retries=3, backoff=2):
    """
    Decorador para reintentar llamadas a APIs externas.
    Ej: Podio y QuickBooks.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = backoff

            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)

                except Exception as e:
                    if _es_permanente(e):
                        logger.error("[retry_api] Fallo permanente, no se reintenta: %s", e)
                        raise
                    logger.error(
                        f"[retry_api] Error en intento {attempt}/{max_retries}: {e}",
                        exc_info=True
                    )

                    if attempt == max_retries:
                        logger.critical("[retry_api] Falló permanentemente.")
                        raise

                    logger.info(
                        f"[retry_api] Reintentando en {delay} segundos...")
                    time.sleep(delay)
                    delay *= 2  # backoff exponencial

        return wrapper

    return decorator


def retry_db(max_retries=3, delay=1):
    """
    Decorador para operaciones de base de datos susceptibles a errores temporales.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):

            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)

                except Exception as e:
                    logger.error(
                        f"[retry_db] Error en intento {attempt}/{max_retries}: {e}",
                        exc_info=True
                    )

                    # Sin rollback, la sesión queda envenenada y TODOS los
                    # reintentos mueren con PendingRollbackError (failed_sync
                    # #12): el primer arg de save/delete_with_retry es la
                    # sesión — límpiala antes de reintentar o propagar.
                    _session = args[0] if args else None
                    if hasattr(_session, "rollback"):
                        try:
                            _session.rollback()
                        except Exception:
                            pass

                    if attempt == max_retries:
                        logger.critical(
                            "[retry_db] Falló permanentemente con DB.")
                        raise

                    time.sleep(delay)

        return wrapper

    return decorator
