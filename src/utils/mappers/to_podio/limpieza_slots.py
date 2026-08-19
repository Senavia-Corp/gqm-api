"""Un hueco que la app no puede rellenar NO se manda a Podio.

Contexto (18-ago-2026). Los tres mappers de salida escribían `[]` en todo campo
que la base no supiera rellenar, y `clean_podio_fields` conserva ese `[]` a
propósito. En Podio, `[]` significa **borra el campo**. Medido contra
producción: 6.497 QID recibían el borrado de sus 13 huecos `materials-purchased-*`
y sus 3 `bldg-*` en cada `PATCH /jobs/<id>?sync_podio=true`; 6.438 recibían
además el borrado de `bldg-dept`, y 634 jobs de los tres tipos el de
`relationship` (el cliente). La base solo tenía 1 alquiler aprobado, 2 BD fees y
11 compras para 7.591 jobs, así que casi nunca podía rellenar nada.

La regla del cliente (Sebastian, 18-ago-2026) es simétrica y aquí aplica igual:
**un campo vacío no es un dato, es la ausencia de dato.** Que la app no conozca
un valor no autoriza a borrarlo en Podio.

Así que el borrado deja de ser implícito y pasa a ser un acto explícito: quien
quiera vaciar un campo lo pide por `limpiar_slots`. Es el mismo canal que usa la
ruta de borrado de un coste para liberar su hueco.
"""
from typing import Iterable, Optional


def normalizar(limpiar_slots: Optional[Iterable[str]]) -> frozenset[str]:
    """Los `external_id` que ESTA llamada quiere vaciar en Podio."""
    return frozenset(limpiar_slots or ())


def asignar(payload: dict, ext_id: str, convertido, limpiar: frozenset[str]) -> None:
    """Coloca `convertido` en el payload, o vacía el campo si se pidió.

    - hay valor            → se escribe
    - no hay y se pidió    → `[]`, que en Podio borra el campo
    - no hay y no se pidió → la clave **no aparece**, y Podio no lo toca
    """
    if convertido is not None:
        payload[ext_id] = convertido
    elif ext_id in limpiar:
        payload[ext_id] = []
