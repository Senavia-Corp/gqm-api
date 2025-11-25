
import time
import functools
from src.utils.middleware.logs import logger


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

                    if attempt == max_retries:
                        logger.critical(
                            "[retry_db] Falló permanentemente con DB.")
                        raise

                    time.sleep(delay)

        return wrapper

    return decorator
