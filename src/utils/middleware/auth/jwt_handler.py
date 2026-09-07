"""Emisión y verificación de los JWT de sesión.

O-07 (auditoría de portal) — las claves se leían con `os.getenv` en el MOMENTO
DEL IMPORT, y quien mete el `.env` en `os.environ` es `load_dotenv()` dentro de
`src/config.py`. Si este módulo se importaba ANTES que `src.config`, ambas
claves quedaban congeladas en `None` y ya no había forma de arreglarlo: cargar
el `.env` después no cambia una variable de módulo ya evaluada.

Reproducido en una línea:

    >>> import src.utils.middleware.auth.jwt_handler as jh
    >>> jh.LOGIN_SECRET_KEY
    None
    >>> import src.config          # aquí sí se carga el .env
    >>> jh.LOGIN_SECRET_KEY        # pero el módulo ya capturó el None
    None

Con la clave a `None`, `jwt.encode` revienta con
`TypeError: Expected a string value` desde dentro de PyJWT —un 500 en
`/auth/login` que no menciona ninguna variable de entorno— y `jwt.decode`, que
se traga toda excepción, devuelve `None`: TODA petición autenticada pasa a 401
sin dejar ni una pista de por qué. La segunda mitad es la peor.

Hoy la aplicación funciona porque `main.py` importa `src.config` pronto. Eso es
suerte de orden de imports, no un diseño: cualquier refactor que la cambie deja
el inicio de sesión roto con un mensaje que apunta a PyJWT. Y si mañana falta
`LOGIN_SECRET_KEY` en el entorno de producción, el síntoma sería el mismo error
opaco en lugar de decir qué falta.

Las claves pasan a leerse EN CADA USO, primero de `os.environ` y si no del
`.env` (vía `decouple`, que no necesita que nadie haya llamado a `load_dotenv`),
y su ausencia se convierte en un error que dice exactamente qué falta.
"""
import os
from datetime import datetime, timedelta, timezone

import jwt

ALGORITHM = "HS256"


class ClaveJWTAusente(RuntimeError):
    """Falta una clave de firma en el entorno. No es un token inválido."""


def _entero_de_entorno(nombre: str, por_defecto: int) -> int:
    crudo = os.environ.get(nombre)
    if crudo is None:
        from decouple import config as _config
        crudo = _config(nombre, default=None)
    try:
        return int(crudo) if crudo not in (None, "") else por_defecto
    except (TypeError, ValueError):
        return por_defecto


def _clave(nombre: str) -> str:
    """La clave de firma, leída en el momento de usarla.

    Se mira `os.environ` primero —es lo que rellena `load_dotenv()` y lo que
    inyecta Vercel— y si no está, el `.env` directamente. Así el valor es
    correcto venga de donde venga y sin depender del orden de los imports.
    """
    valor = os.environ.get(nombre)
    if not valor:
        from decouple import config as _config
        valor = _config(nombre, default="")
    if not valor:
        raise ClaveJWTAusente(
            f"Falta {nombre} en el entorno: no se pueden firmar ni verificar "
            f"tokens de sesión. Defínela en el .env o en las variables del "
            f"despliegue.")
    return valor


# Compatibilidad: había código y pruebas leyendo estos nombres del módulo.
# Ahora son propiedades del módulo, no fotos del arranque.
def __getattr__(nombre):
    if nombre in ("LOGIN_SECRET_KEY", "REFRESH_SECRET_KEY"):
        return _clave(nombre)
    if nombre == "ACCESS_EXPIRE_MIN":
        return _entero_de_entorno("ACCESS_TOKEN_EXPIRES_MIN", 60)
    if nombre == "REFRESH_EXPIRE_DAYS":
        return _entero_de_entorno("REFRESH_TOKEN_EXPIRES_DAYS", 7)
    raise AttributeError(nombre)


def create_access_token(data: dict):
    payload = data.copy()
    minutos = _entero_de_entorno("ACCESS_TOKEN_EXPIRES_MIN", 60)
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutos)
    payload.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    })
    return jwt.encode(payload, _clave("LOGIN_SECRET_KEY"), algorithm=ALGORITHM)


def create_refresh_token(data: dict):
    payload = data.copy()
    dias = _entero_de_entorno("REFRESH_TOKEN_EXPIRES_DAYS", 7)
    expire = datetime.now(timezone.utc) + timedelta(days=dias)
    payload.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh"
    })
    return jwt.encode(payload, _clave("REFRESH_SECRET_KEY"), algorithm=ALGORITHM)


def decode_access_token(token: str):
    """`None` si el token no vale. Una clave AUSENTE no es eso: sube.

    El `except Exception` de antes tapaba las dos cosas con el mismo `None`, y
    un despliegue sin `LOGIN_SECRET_KEY` se manifestaba como «todo el mundo
    tiene la sesión caducada» en vez de como un fallo de configuración.
    """
    clave = _clave("LOGIN_SECRET_KEY")
    try:
        return jwt.decode(token, clave, algorithms=[ALGORITHM])
    except Exception:
        return None


def decode_refresh_token(token: str):
    clave = _clave("REFRESH_SECRET_KEY")
    try:
        return jwt.decode(token, clave, algorithms=[ALGORITHM])
    except Exception:
        return None
