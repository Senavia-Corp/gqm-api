"""Vacía la ventana del limitador de login. SOLO para el arnés, SOLO en dev.

`scripts/verificar_portal.sh` encadena seis bloques y varios de ellos autentican
a los mismos siete sujetos: la matriz, el escáner de fugas, el flujo e2e y luego
cada módulo de pytest. El limitador son 5 intentos por (IP, correo) en 60 s
(`Login_auth.py:46-47`), así que el guion se bloquea a sí mismo: medido, el
bloque 4 abortaba con `AssertionError` en el login de `sub-dev` y dos pruebas de
perfil ni llegaban a ejecutarse — un rojo que no habla del producto.

Las alternativas eran peores: subir el límite por entorno apaga de paso las dos
pruebas que verifican el limitador, y esperar 60 s entre bloques alarga el
veredicto sin ganar nada. `login_attempt` es una tabla de filas efímeras que el
propio limitador va podando; vaciarla entre bloques no toca ni una línea de la
regla, y su prueba dedicada sigue creando su propia ráfaga.

La compuerta de aislamiento se aplica igual: aquí no se entra contra producción.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decouple import config  # noqa: E402
from sqlmodel import delete  # noqa: E402

from src.database.db_sqlmodel import get_session  # noqa: E402
from src.models.LoginAttemptModel import LoginAttempt  # noqa: E402
from src.utils.db_guard import require_dev_database  # noqa: E402

require_dev_database(config, contexto="limpiar ventana de login")

with get_session() as sesion:
    borradas = sesion.exec(delete(LoginAttempt)).rowcount
    sesion.commit()
print(f"  (limitador de login: {borradas} intentos en ventana descartados)")
