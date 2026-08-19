"""Acceso al mapa de huecos de cuotas a técnico.

El mapa lo produce `scripts/generar_mapa_pagos.py` leyendo el esquema real de
las 12 apps de producción, y vive en `payment_slots.json` **como dato**, no como
código. Así el diff se lee como lo que es, y la prueba puede regenerarlo y
compararlo para detectar una edición a mano.

## El mapa va cuñado por (tipo, año)

`TECH_PAYMENT_FIELDS`, el diccionario que esto sustituye, no distinguía años, e
incluía `tech-3-payment-*` y `tech-4-payment-*` — que **no existen en PAR 2023**
ni el técnico 4 en PAR 2024. Era un bug latente: escribir ahí habría dado
`field.not.found`.

## El fichero tiene que llegar al bundle

`vercel.json` no declara `includeFiles`, así que un `.json` que sólo se abre en
tiempo de ejecución podría no subir. Por eso la carga es **al importar** y falla
ruidosamente: es preferible que el arranque se caiga a que los pagos dejen de
sincronizar en silencio.
"""
import json
import pathlib
from typing import Optional

_RUTA = pathlib.Path(__file__).with_name("payment_slots.json")

try:
    _DATOS = json.loads(_RUTA.read_text())
except (OSError, ValueError) as e:  # pragma: no cover - se comprueba en el smoke test
    raise RuntimeError(
        f"No se pudo cargar el mapa de cuotas ({_RUTA}): {e}. "
        f"Si esto ocurre en Vercel, el .json no llegó al bundle: revisa "
        f"`includeFiles` en vercel.json. Regenerarlo: "
        f"python scripts/generar_mapa_pagos.py --escribir"
    ) from e


def habilitado(job_type: str) -> bool:
    """¿Este tipo de job usa cuotas parciales?

    PTL está a `false` por decisión de cliente, expresada como dato para que se
    vea en el artefacto en vez de esconderse en un `if`."""
    return bool(_DATOS["apps"].get((job_type or "").upper(), {}).get("habilitado"))


def _anios(job_type: str) -> dict:
    return _DATOS["apps"].get((job_type or "").upper(), {}).get("anios", {})


def _del_anio(job_type: str, year: Optional[int]) -> dict:
    anios = _anios(job_type)
    if not anios:
        return {}
    clave = str(year) if year is not None and str(year) in anios else max(anios, key=int)
    return anios[clave]


def anios_disponibles(job_type: str) -> list[int]:
    return sorted(int(a) for a in _anios(job_type))


def mapa_pagos(job_type: str, year: Optional[int] = None) -> dict[int, dict[int, str]]:
    """`{tech_index: {cuota: external_id}}` para ese tipo y año."""
    techs = _del_anio(job_type, year).get("techs", {})
    return {int(t): {int(c): e for c, e in d["cuotas"].items()} for t, d in techs.items()}


def slot_de_cuota(job_type: str, year: Optional[int], tech_index: int,
                  cuota: int) -> Optional[str]:
    return mapa_pagos(job_type, year).get(tech_index, {}).get(cuota)


def cuota_de_slot(job_type: str, year: Optional[int],
                  external_id: str) -> Optional[tuple[int, int]]:
    """`(tech_index, cuota)` a partir del `external_id`, o `None`."""
    for tech, cuotas in mapa_pagos(job_type, year).items():
        for cuota, ext in cuotas.items():
            if ext == external_id:
                return tech, cuota
    return None


def campo_check_numbers(job_type: str, year: Optional[int],
                        tech_index: int) -> Optional[str]:
    """El `Check Number(s)` de la sección del técnico. Es **uno por sección**,
    no uno por cuota, así que la app lo LEE y nunca lo escribe: componerlo desde
    N cuotas pisaría lo que alguien escribió a mano."""
    techs = _del_anio(job_type, year).get("techs", {})
    entrada = techs.get(str(tech_index))
    return entrada.get("check_numbers") if entrada else None


def collect_payment_slots(fields: list, job_type: str,
                          year: Optional[int] = None) -> dict:
    """`{tech_index: {cuota: importe}}` leído del ítem de Podio.

    Mantiene el nombre y el orden de los dos primeros argumentos de la función
    que sustituye, para no romper a sus llamadores. Sólo devuelve las cuotas que
    **vienen con importe**: una cuota ausente o vacía no entra, y por tanto no
    puede borrar nada aguas abajo (regla del vacío).
    """
    if not habilitado(job_type):
        return {}

    por_slot = {}
    for f in fields or []:
        ext = (f.get("external_id") or "")
        crudo = f.get("values") or []
        if not ext or not crudo:
            continue
        v = crudo[0].get("value", crudo[0]) if isinstance(crudo[0], dict) else crudo[0]
        if isinstance(v, dict) and "value" in v:
            v = v["value"]
        try:
            por_slot[ext] = float(v)
        except (TypeError, ValueError):
            continue

    fuera: dict[int, dict[int, float]] = {}
    for tech, cuotas in mapa_pagos(job_type, year).items():
        for cuota, ext in cuotas.items():
            if ext in por_slot:
                fuera.setdefault(tech, {})[cuota] = por_slot[ext]
    return fuera


# Compatibilidad: `TECH_PAYMENT_FIELDS` era `{job_type: {tech: [ext, ...]}}`.
# Se construye desde el artefacto (año más reciente) para no romper los imports
# que aún existen. DEPRECADO — usar `mapa_pagos`, que sí distingue el año.
TECH_PAYMENT_FIELDS = {
    tipo: {tech: [cuotas[c] for c in sorted(cuotas)]
           for tech, cuotas in mapa_pagos(tipo).items()}
    for tipo in _DATOS["apps"] if habilitado(tipo)
}
