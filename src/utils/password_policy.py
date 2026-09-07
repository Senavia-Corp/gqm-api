"""Politica de contrasenas (O-01 de la auditoria de portal).

Medido antes del arreglo: `POST /technician/` aceptaba `"1"`, `"abc"`,
`"password"` y `"12345678"` — las cuatro devolvian 201. No habia longitud
minima, ni comprobacion de diccionario, ni de complejidad, en servidor.

Importa ahora y no dentro de seis meses porque el alta del portal son 432
subcontratistas con contrasena escrita a mano por un administrador.
"""
import re

LONGITUD_MINIMA = 10

# No es una lista exhaustiva —eso es trabajo de un diccionario real— sino el
# corte barato que atrapa lo que de verdad se teclea cuando hay 432 altas que
# despachar y nadie mira.
CONTRASENAS_PROHIBIDAS = frozenset({
    "password", "contrasena", "contraseña", "12345678", "123456789", "1234567890",
    "qwertyui", "abcd1234", "admin123", "gqm12345", "password1", "password123",
    "welcome1", "changeme", "letmein1", "iloveyou", "senavia1", "subcontractor",
})


class PasswordDebil(ValueError):
    """La contrasena no cumple la politica. El mensaje es para el administrador."""


def validar_password(password: str, *, campo: str = "Password") -> None:
    """Lanza `PasswordDebil` si no cumple. No devuelve nada si cumple.

    Se valida en SERVIDOR a proposito: la pantalla de alta la rellena un
    administrador, y una comprobacion solo en el panel no protege de un `curl`
    ni de una importacion masiva.
    """
    if password is None or not isinstance(password, str) or not password.strip():
        raise PasswordDebil(f"{campo}: no puede estar vacia.")
    if len(password) < LONGITUD_MINIMA:
        raise PasswordDebil(
            f"{campo}: debe tener al menos {LONGITUD_MINIMA} caracteres "
            f"(tiene {len(password)}).")
    if password.lower() in CONTRASENAS_PROHIBIDAS:
        raise PasswordDebil(f"{campo}: es una contrasena demasiado comun.")
    # El caracter repetido se mira ANTES que las clases, y no despues.
    #
    # Detras iba era codigo muerto: una cadena de un solo caracter repetido
    # tiene por definicion UNA sola clase de caracter, asi que la regla de las
    # 3 de 4 saltaba siempre primero y esta no llegaba a evaluarse nunca. Lo
    # destapo la prueba de cobertura del contrato del espejo, que exige que
    # cada regla sea alcanzable como PRIMER motivo de rechazo.
    #
    # Delante, ademas de estar viva, da el mensaje util: a quien teclea
    # "aaaaaaaaaa" le sirve mas «no puede ser un unico caracter repetido» que
    # «combina 3 de estos 4 tipos». El veredicto no cambia: las dos rechazan.
    if re.fullmatch(r"(.)\1+", password):
        raise PasswordDebil(f"{campo}: no puede ser un unico caracter repetido.")
    clases = sum(bool(re.search(patron, password))
                 for patron in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))
    if clases < 3:
        raise PasswordDebil(
            f"{campo}: debe combinar al menos 3 de estos 4 tipos de caracter: "
            f"minuscula, mayuscula, digito y simbolo.")
