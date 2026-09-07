"""O-06 bis · La gemela del contrato del espejo.

`gqm-panel-admin/lib/password-policy.ts` reproduce `src/utils/password_policy.py`.
Dos implementaciones de la misma regla se separan sin que nadie lo note, y ya
pasó dos veces en el mismo diff: la longitud en unidades UTF-16 frente a puntos
de codigo (`'Ab1🙂🙂🙂🙂'` medía 7 aquí y 11 allí), y el orden de comprobación,
que daba motivos distintos en 11 de 50 casos.

Esta tabla congela el veredicto Y EL MOTIVO de ESTE modulo para 51 entradas. Su
gemela vive en el panel, en `tests/rbac/password_contract.spec.ts`, con el mismo
corpus y afirmando lo mismo contra TypeScript.

LIMITE DECLARADO: son dos copias. Si alguien cambia la politica de aqui, esta
prueba se pone roja y le recuerda que hay un espejo; si alguien toca el espejo,
la otra. Lo que ninguna ve por si sola es que las dos tablas se separen entre
ellas — por eso llevan el mismo comentario y cambiarlas es un solo commit.
"""
import pytest

from src.utils.password_policy import (
    CONTRASENAS_PROHIBIDAS,
    PasswordDebil,
    validar_password,
)

# [contrasena, ¿la acepta?, clave de la primera regla que falla]
CONTRATO = [
    ["", False, "vacia"],
    [" ", False, "vacia"],
    ["a", False, "longitud"],
    ["1", False, "longitud"],
    ["abc", False, "longitud"],
    ["password", False, "longitud"],
    ["PASSWORD", False, "longitud"],
    ["12345678", False, "longitud"],
    ["Abcdefg1", False, "longitud"],
    ["Abcdefgh1", False, "longitud"],
    ["Abcdefghi1", True, None],
    ["abcdefghij", False, "clases"],
    ["abcdefghij1", False, "clases"],
    ["ABCDEFGHIJ1", False, "clases"],
    ["aaaaaaaaaaaa", False, "repetida"],
    ["AAAAAAAAAA", False, "repetida"],
    ["!!!!!!!!!!", False, "repetida"],
    ["Cl4ve-Buena!2026", True, None],
    ["contraseña1A", True, None],
    ["Contraseña!1", True, None],
    ["ñññññññññññ", False, "repetida"],
    ["Ab1🙂🙂🙂🙂", False, "longitud"],
    ["🙂🙂🙂🙂🙂🙂🙂🙂🙂🙂", False, "repetida"],
    ["Ab1!🙂🙂🙂🙂🙂🙂", True, None],
    ["Ab1!456789", True, None],
    ["ab1!456789", True, None],
    ["AB1!456789", True, None],
    ["Abcdefghij", False, "clases"],
    ["Abcdefghi!", True, None],
    ["abcdefghi1", False, "clases"],
    ["  Abcdefghi1  ", True, None],
    ["Password1!", True, None],
    ["welcome1", False, "longitud"],
    ["Welcome1", False, "longitud"],
    ["changeme", False, "longitud"],
    ["CHANGEME", False, "longitud"],
    ["senavia1", False, "longitud"],
    ["SENAVIA1", False, "longitud"],
    ["gqm12345", False, "longitud"],
    ["admin123", False, "longitud"],
    ["letmein1", False, "longitud"],
    ["iloveyou", False, "longitud"],
    ["subcontractor", False, "comun"],
    ["SUBCONTRACTOR", False, "comun"],
    ["qwertyui", False, "longitud"],
    ["abcd1234", False, "longitud"],
    ["password123", False, "comun"],
    ["1234567890", False, "comun"],
    ["123456789", False, "longitud"],
    ["Ab1!", False, "longitud"],
    ["Ab1!5678901234567890", True, None],
]


# El motivo se lee del MENSAJE que lanza el servidor, no de una copia de su
# orden de comprobacion. Reimplementar el orden aqui era duplicarlo: al mover
# la regla del caracter repetido delante de la de clases, esta copia se quedo
# vieja y la prueba senalo un cambio que no existia. Leyendo el mensaje, la
# prueba mide LO QUE HACE el servidor y no lo que alguien creyo que hacia.
# Las agujas son EXCLUYENTES entre si a proposito: «al menos» a secas casaba
# tanto con «debe tener al menos N caracteres» como con «debe combinar al menos
# 3 de estos 4 tipos», y clasificaba mal la mitad de los casos.
_MOTIVO_POR_MENSAJE = (
    ("no puede estar vacia", "vacia"),
    ("demasiado comun", "comun"),
    ("caracter repetido", "repetida"),
    ("3 de estos 4 tipos", "clases"),
    ("debe tener al menos", "longitud"),
)


def _clave_del_fallo(p):
    """La primera regla que falla, segun lo que dice el propio servidor."""
    try:
        validar_password(p)
    except PasswordDebil as fallo:
        mensaje = str(fallo)
        for aguja, clave in _MOTIVO_POR_MENSAJE:
            if aguja in mensaje:
                return clave
        raise AssertionError(f"mensaje sin motivo reconocible: {mensaje!r}")
    return None


def test_la_politica_sigue_diciendo_lo_que_dice_el_contrato():
    divergencias = []
    for password, valida, motivo in CONTRATO:
        try:
            validar_password(password)
            mia = True
        except PasswordDebil:
            mia = False
        mi_motivo = _clave_del_fallo(password)
        if mia != valida or mi_motivo != motivo:
            divergencias.append(
                f"{password!r}: contrato {{valida:{valida}, motivo:{motivo}}} "
                f"· real {{valida:{mia}, motivo:{mi_motivo}}}")
    # Se ENUMERAN, no se cuentan: «0 == 0» taparia un fallo compensado por otro.
    assert divergencias == [], (
        "la politica cambio. Si es a proposito, regenera TAMBIEN el contrato "
        "del panel (tests/rbac/password_contract.spec.ts):\n  "
        + "\n  ".join(divergencias))


def test_el_contrato_cubre_de_verdad_lo_que_importa():
    """Sin esto, vaciar la tabla dejaria la prueba de arriba verde: una tabla
    sin filas no tiene divergencias."""
    assert len(CONTRATO) >= 50
    assert {m for _, _, m in CONTRATO} == {
        "vacia", "longitud", "comun", "clases", "repetida", None}
    # Y al menos una que SI se acepta: una tabla de puros rechazos pasaria con
    # una politica que rechazara absolutamente todo.
    assert any(v for _, v, _ in CONTRATO)


@pytest.mark.parametrize("prohibida", sorted(CONTRASENAS_PROHIBIDAS))
def test_toda_la_lista_de_prohibidas_se_rechaza(prohibida):
    """La lista tiene que servir para algo. Se recorre ENTERA, no una muestra:
    una entrada que colara seria justo la que alguien teclearia."""
    with pytest.raises(PasswordDebil):
        validar_password(prohibida)
