"""Cifrado de tokens en reposo (REG-113) — Fernet con clave en env.

Ventana de migración: si un valor guardado no descifra (plaintext legado),
se devuelve tal cual; el próximo guardado ya lo cifra. Sin FERNET_KEY el
módulo opera en passthrough con WARNING (dev sin configurar ≠ crash).
"""
from cryptography.fernet import Fernet, InvalidToken
from decouple import config

from src.utils.middleware.logs.logs import logger

_key = config("FERNET_KEY", default="")
_fernet = Fernet(_key.encode()) if _key else None

if not _fernet:
    if config("APP_ENV", default="production") == "production":
        # Fail-closed en producción: desplegar sin cifrado activo no es
        # aceptable (mismo criterio que SECRET_KEY en main.py).
        raise RuntimeError("FERNET_KEY es obligatoria en producción (cifrado de tokens QBO)")
    logger.warning("FERNET_KEY no configurada: los tokens se guardan SIN cifrar")


def encrypt_token(value):
    if not value or not _fernet:
        return value
    return _fernet.encrypt(value.encode()).decode()


def decrypt_token(value):
    if not value or not _fernet:
        return value
    try:
        return _fernet.decrypt(value.encode()).decode()
    except InvalidToken:
        return value  # plaintext legado — se re-cifra en el próximo guardado
