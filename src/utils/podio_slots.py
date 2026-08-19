"""Catálogo único de los «huecos» de campo de Podio y quién los ocupa.

## El problema que resuelve

Varios registros de la app ocupan un hueco de campo en Podio, y hasta ahora esa
correspondencia se deducía **por posición**: el primer alquiler aprobado iba a
`PURCHASE 1`, el segundo a `PURCHASE 2`, el primer BD fee a `bldg-fees-1`…
Desaprobar el primero corría a todos los siguientes, y vaciar un hueco
intermedio en Podio reasignaba importes entre registros distintos.

El patrón correcto **ya existía en el repo**: `ChangeOrder.podio_field` y
`Order.tech_field` guardan el `external_id` que ocupan, y por eso los change
orders se comportan bien — borrar uno libera *su* hueco sin mover a los demás, y
al agotarse los huecos la API responde 400 sin guardar nada.

Este módulo extiende ese patrón a `EstimateCost` (alquileres y BD fees) y a
`Purchase`, y de paso pone en **un solo sitio** los `external_id` que hoy están
duplicados en tres (`to_podio/job_fields_map.py`, `webhook/jobs_hook_sync.py` y
el orden implícito de `qid_mapper.py`).

## Las dos reglas

1. **El orden de `external_ids` ES el orden de los huecos en Podio.** Se toma de
   `BASE_QID_FIELDS` para que no haya dos listas que puedan divergir.
2. **`reservar` mira la base Y el ítem de Podio.** Producción tiene 22 compras
   en la base contra 7.591 jobs con materiales cargados a mano: si sólo se
   mirase la base, el primer purchase de cualquier job tomaría el hueco 1 y
   **pisaría** lo que el cliente ya tiene en Podio.
"""
from dataclasses import dataclass, field as _dc_field
from typing import Any, Callable, Optional

from sqlmodel import select

from src.models.EstimateCostModel import EstimateCost
from src.models.PurchaseModel import Purchase
from src.utils.mappers.to_podio.job_fields_map import BASE_QID_FIELDS
from src.utils.mappers.to_podio.order_changeorder_mappers import find_next_available_field


@dataclass(frozen=True)
class Propietario:
    """Un tipo de registro que puede ocupar huecos de una familia."""

    modelo: type
    attr_importe: str                      # de dónde sale el importe que va a Podio
    filtro: Optional[Callable[[], Any]] = None   # p. ej. Cost_type == "Rent"
    orden_grupo: int = 0                   # los alquileres van antes que las compras
    crea_desde_podio: bool = False         # ¿un hueco no reclamado crea registro?
    titulo_nuevo: str = ""                 # plantilla del Title al crearlo

    def consulta(self, id_jobs: str):
        q = select(self.modelo).where(self.modelo.ID_Jobs == id_jobs)
        if self.filtro is not None:
            q = q.where(self.filtro())
        return q.order_by(self.modelo.__mapper__.primary_key[0])


@dataclass(frozen=True)
class Familia:
    """Un grupo de huecos de Podio que se reparten entre uno o más modelos."""

    clave: str
    job_type: str
    external_ids: tuple[str, ...]
    propietarios: tuple[Propietario, ...]
    tipo_podio: str = "money"

    def indice(self, ext_id: str) -> Optional[int]:
        try:
            return self.external_ids.index(ext_id)
        except ValueError:
            return None


def _ext_ids(attr: str) -> tuple[str, ...]:
    """Los external_id de un campo `multi`, en el orden en que están declarados."""
    return tuple(BASE_QID_FIELDS[attr]["external_ids"])


_RENT = Propietario(
    modelo=EstimateCost,
    attr_importe="Client_price",
    filtro=lambda: (EstimateCost.Cost_type == "Rent") & (EstimateCost.Status == "Approved"),
    orden_grupo=0,
    crea_desde_podio=False,
)

_COMPRA = Propietario(
    modelo=Purchase,
    attr_importe="Total_spending",
    orden_grupo=1,
    crea_desde_podio=False,   # nunca creamos compras fantasma desde Podio
)

_BDF = Propietario(
    modelo=EstimateCost,
    attr_importe="Client_price",
    filtro=lambda: (EstimateCost.Cost_type == "BDF") & (EstimateCost.Status == "Approved"),
    orden_grupo=0,
    crea_desde_podio=True,
    titulo_nuevo="Bldg Dept Fee {n} (Podio)",
)

FAMILIAS: dict[str, Familia] = {
    "QID.bldg_dept_fees": Familia(
        clave="QID.bldg_dept_fees",
        job_type="QID",
        external_ids=_ext_ids("Bldg_dept_fees"),
        propietarios=(_BDF,),
    ),
    "QID.purchases_list": Familia(
        clave="QID.purchases_list",
        job_type="QID",
        external_ids=_ext_ids("Purchases_list"),
        propietarios=(_RENT, _COMPRA),
    ),
}

# Qué familia le corresponde a un EstimateCost según su tipo de coste.
FAMILIA_POR_COST_TYPE = {
    "BDF": "QID.bldg_dept_fees",
    "Rent": "QID.purchases_list",
}


def familia(clave: str) -> Familia:
    return FAMILIAS[clave]


def familia_de_coste(cost_type: Optional[str]) -> Optional[Familia]:
    clave = FAMILIA_POR_COST_TYPE.get((cost_type or "").strip())
    return FAMILIAS[clave] if clave else None


# --------------------------------------------------------------- lecturas


def registros(session, fam: Familia, id_jobs: str) -> list:
    """Todos los registros que compiten por los huecos de la familia, en el
    orden histórico (alquileres antes que compras, y dentro de cada grupo por
    clave primaria). Ese orden es el que replica el reparto posicional de hoy."""
    salida = []
    for p in sorted(fam.propietarios, key=lambda x: x.orden_grupo):
        salida.extend(session.exec(p.consulta(id_jobs)).all())
    return salida


def _importe(fam: Familia, registro) -> Optional[float]:
    for p in fam.propietarios:
        if isinstance(registro, p.modelo):
            # dos propietarios pueden compartir modelo (Rent y BDF son ambos
            # EstimateCost); el atributo de importe es el mismo, así que vale.
            v = getattr(registro, p.attr_importe, None)
            return None if v is None else float(v)
    return None


def ocupados(session, fam: Familia, id_jobs: str, excluir_pk=None) -> dict[str, Any]:
    """`{external_id: registro}` de los huecos que alguien declara ocupar."""
    fuera = {}
    for r in registros(session, fam, id_jobs):
        slot = getattr(r, "podio_field", None)
        if not slot or slot not in fam.external_ids:
            continue
        if excluir_pk is not None and _pk(r) == excluir_pk:
            continue
        fuera[slot] = r
    return fuera


def _pk(registro):
    return getattr(registro, registro.__mapper__.primary_key[0].name, None)


def libres_en_bd(session, fam: Familia, id_jobs: str, excluir_pk=None) -> list[str]:
    """Los huecos que ningún registro declara. Comprobación barata, sin red:
    sirve para responder 400 antes de guardar nada."""
    tomados = ocupados(session, fam, id_jobs, excluir_pk=excluir_pk)
    return [e for e in fam.external_ids if e not in tomados]


def payload_por_slot(session, fam: Familia, id_jobs: str) -> dict[str, float]:
    """`{external_id: importe}` de los registros que declaran su hueco.

    Los que no lo declaran (aún sin backfill) NO salen: de eso se encarga
    `slots_legacy_posicionales`."""
    salida = {}
    for slot, r in ocupados(session, fam, id_jobs).items():
        v = _importe(fam, r)
        if v is not None:
            salida[slot] = v
    return salida


def slots_legacy_posicionales(session, fam: Familia, id_jobs: str) -> dict[str, float]:
    """El reparto por posición de siempre, **sólo** para los registros que aún
    no declaran hueco.

    Es la red que hace que ningún estado intermedio del despliegue sea peor que
    hoy: con la columna recién añadida y todo a NULL, esto devuelve exactamente
    lo que el mapper calculaba antes. Desaparece cuando el backfill deje 0 NULLs.
    """
    todos = registros(session, fam, id_jobs)
    declarados = {getattr(r, "podio_field", None) for r in todos}
    disponibles = [e for e in fam.external_ids if e not in declarados]

    salida = {}
    for r in todos:
        if getattr(r, "podio_field", None):
            continue
        if not disponibles:
            break
        v = _importe(fam, r)
        slot = disponibles.pop(0)
        if v is not None:
            salida[slot] = v
    return salida


# --------------------------------------------------------------- escrituras


def reservar(session, fam: Familia, id_jobs: str, registro,
             podio_fields: Optional[dict] = None) -> Optional[str]:
    """Asigna al registro el primer hueco libre y lo guarda en `podio_field`.

    Descarta los huecos tomados **en la base** y, si se le pasan los campos del
    ítem, también los que ya tienen valor **en Podio**. Devuelve el
    `external_id` asignado, o `None` si no queda ninguno (y entonces el llamador
    debe responder 400 sin guardar nada, como hacen los change orders).
    """
    if getattr(registro, "podio_field", None):
        return registro.podio_field

    tomados_bd = set(ocupados(session, fam, id_jobs, excluir_pk=_pk(registro)))
    candidatos = [e for e in fam.external_ids if e not in tomados_bd]
    if not candidatos:
        return None

    if podio_fields is None:
        slot = candidatos[0]
    else:
        slot = find_next_available_field(podio_fields, candidatos)
        if slot is None:
            return None

    registro.podio_field = slot
    session.add(registro)
    return slot


def liberar(session, registro) -> Optional[str]:
    """Suelta el hueco de un registro que se borra o se desaprueba.

    Devuelve el `external_id` que quedó libre para que el llamador se lo pase a
    `sync_job_to_podio(..., limpiar_slots=[slot])`: vaciar en Podio es un acto
    explícito, nunca un efecto colateral."""
    slot = getattr(registro, "podio_field", None)
    if not slot:
        return None
    registro.podio_field = None
    session.add(registro)
    return slot
