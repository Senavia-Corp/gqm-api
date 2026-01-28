# Libreria para hacerle hash a las contraseñas
from passlib.context import CryptContext

# Configuración estándar de argon2 -> nunca genera dos hash iguales
pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto"
)


def hash_password(password: str) -> str:
    # Recibe un password en texto plano y devuelve su hash bcrypt.
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Compara un password enviado con el hash almacenado en la BD.
    Devuelve True si coinciden, False si no.
    """
    return pwd_context.verify(plain_password, hashed_password)
