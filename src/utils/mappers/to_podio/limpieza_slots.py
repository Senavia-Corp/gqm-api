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

from src.utils.mappers.from_podio.job_mapper import CAMPOS_CALCULADOS_EN_LOCAL


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


def es_cero_sin_respaldo(attr: str, value) -> bool:
    """El mismo hueco de siempre, disfrazado de 0 en vez de None.

    Medido en producción el 2-sep-2026. `PATCH /jobs/QID6904?dry_run=true`
    llevaba `estimated-material-total = 0` mientras Podio tenía **437,91**:
    ejecutarlo sin `dry_run` borraba esos 437,91. Los tres totales de QID
    (`estimated-material-total`, `estimated-hoa-admin-total`, `fees-and-cost`)
    y los dos de PTL los reconstruye `job_calculator.recalculate_job_fields`
    desde los `EstimateCost`, así que un job cuyas líneas nunca cruzaron la API
    los tiene a 0 — y ese 0 salía en cada empujón. En la app QID 2026: 227
    ítems con material distinto de 0 en Podio, **165 con 0/NULL en la BD**.

    Es la regla de `asignar` aplicada al caso en que la ausencia de dato no
    llega como None sino como 0: **que la app no conozca un valor no autoriza
    a borrarlo en Podio.** La lista es la misma que ya usa el sentido
    entrante para no vaciar estas columnas (`CAMPOS_CALCULADOS_EN_LOCAL`), de
    modo que ida y vuelta no puedan discrepar sobre qué es un agregado.

    Contrapeso aceptado a sabiendas: si un total baja a 0 de verdad —se borran
    todas sus líneas—, Podio conserva el importe viejo. Vaciar sigue siendo un
    acto explícito y pasa por `limpiar_slots`, igual que en los huecos.
    """
    if attr not in CAMPOS_CALCULADOS_EN_LOCAL:
        return False
    try:
        return float(value) == 0
    except (TypeError, ValueError):
        return False
