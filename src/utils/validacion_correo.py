"""El formato de `Email_Address`, que es el NOMBRE DE USUARIO de acceso.

Los tres principales —technician, subcontractor y member— declaraban
`Email_Address: str` sin ninguna validación de formato. Medido con curl y un
token de administrador:

    PATCH /technician/TEC60187 {"Email_Address": "esto-no-es-un-correo"}
    → 200, y el cuerpo devuelve el valor tal cual.

El duplicado sí estaba atajado (índice único de `e9c1correo` → 409), pero el
FORMATO no. Toda la familia O-02/O-04/O-05 se ocupa de que el correo sea único
y de que se busque igual; nadie comprobaba que fuera un correo.

Por qué importa justo ahora: en el alta de los 432 subcontratistas —o desde el
formulario de edición del técnico, que expone el campo— basta con que alguien
teclee un teléfono en la casilla equivocada para que la cuenta quede sin
ninguna vía de acceso. El sub no puede entrar (no acierta su «correo») y la
recuperación por correo manda el enlace a una dirección que no existe. Es una
cuenta muerta que nadie detecta hasta que su dueño llama.

Deliberadamente PERMISIVO. No se implementa el RFC 5322: el objetivo es
descartar lo que evidentemente no es una dirección —un teléfono, un nombre, una
cadena con espacios— sin rechazar direcciones raras pero legítimas. Rechazar de
más aquí rompería altas válidas, que es peor que la fuga que se quiere cerrar.

Tampoco se toca el caso VACÍO: hoy se puede crear una fila sin correo y hay
datos así; convertir eso en un 400 es una decisión de producto, no un arreglo
de la auditoría, y rompería el alta masiva desde Podio.
"""
import re

# Un `@`, algo a cada lado, un punto en el dominio, y ningún espacio.
_FORMA = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validar_formato_correo(valor):
    """Validador de pydantic para `Email_Address`. Normaliza y comprueba.

    Se le quitan los espacios de los extremos por lo mismo que O-05: un correo
    guardado como `" sub@x.com "` es una cuenta muda —el login lo busca
    normalizado y la fila no aparece— y el índice único de `e9c1correo` ya
    compara con `lower(btrim(...))`, así que guardarlo limpio es lo coherente.
    """
    if valor is None:
        return valor
    limpio = str(valor).strip(" \t\n\r\v\f")
    if limpio == "":
        return valor
    if not _FORMA.match(limpio):
        raise ValueError(
            f"Email_Address={valor!r} no tiene forma de correo electronico. "
            f"Es el nombre de usuario de acceso: si no es una direccion real, "
            f"la cuenta no puede iniciar sesion ni recuperar la contrasena.")
    return limpio
