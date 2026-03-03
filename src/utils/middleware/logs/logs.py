
import logging
import sys


def setup_logger():
    logger = logging.getLogger("app")

    if logger.handlers:
        return logger  # Evita duplicar handlers

    logger.setLevel(logging.DEBUG)  # Este es el nivel mas básico.

    # Formato de los logs
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    )

    # Handler a consola: para mostrar los mensajes en la consola.
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)  # Conecta logger con consola.

    return logger


# Solo lo creamos una vez y lo reutilizamos en toda la app
logger = setup_logger()

'''
Los niveles de Logs son:
 - DEBUG
 - INFO
 - WARNING
 - ERROR
 - CRITICAL

NOTA: En producción se sube el nivel a INFO.
'''
