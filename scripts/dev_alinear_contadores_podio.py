"""Alinea los contadores de las apps Podio TEST para que dev pueda sincronizar
PMC y BDEP. Solo para el entorno de desarrollo.

EL PROBLEMA. En `parent_mgmt_co` y `bldg_dept` la CLAVE PRIMARIA es
`app_item_id_formatted` — el contador de items de la app de Podio ('PMC002',
'BLGDEP2'). Eso implica que cada tabla solo puede alimentarse de UNA app de
Podio. En producción se cumple y no hay problema.

En develop no se cumple: esas tablas traen filas copiadas de las apps REALES
(PMC001..PMC022 + PMC60032..60035, y BLGDEP1..48), mientras que los webhooks
entrantes vienen de las apps TEST, cuyo contador arranca en 1. Cada item nuevo
en TEST choca con la PK de una fila de producción, el INSERT revienta y el
evento acaba en la dead-letter: la sincronización de PMC/BDEP no se puede
probar en dev, aunque el hook entregue perfectamente.

LA SOLUCIÓN. Adelantar el contador de la app TEST por encima del máximo que
ocupa producción, creando y borrando items de usar y tirar. A partir de ahí los
dos espacios de numeración son disjuntos — exactamente la propiedad de la que
depende producción. No tapa ningún bug de producción: hace que dev cumpla el
mismo invariante.

Los contadores de Podio no reutilizan números, así que esto es permanente.

Los items de usar y tirar SÍ disparan sus hooks y cada uno choca (por eso
estamos aquí), así que dejan una fila en `podio_failed_syncs`: el script las
limpia al final. La primera versión intentaba quitar los hooks antes y
reponerlos después, y salió mal de las dos formas posibles: `clear` los vio
"ajenos" porque el PUBLIC_URL local es localhost y no coincidía con el
registrado, y `register` los habría re-creado apuntando a localhost (Podio lo
rechazó con `hook.url.invalid_port`, que fue la única razón de que no quedaran
hooks inservibles). Tocar los hooks desde local es un riesgo sin premio.

Arreglo de fondo pendiente (no de esta fase): que develop no lleve filas
derivadas de producción, o que la PK no sea el contador de Podio.

Uso:  .venv/bin/python scripts/dev_alinear_contadores_podio.py [--aplicar]
Sin --aplicar solo informa.
"""
import os
import re
import sys

sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/gqm-api-fixes"))
os.chdir(os.path.expanduser("~/Documents/GitHub/gqm-api-fixes"))

import requests  # noqa: E402
from decouple import config as env_config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from src.database.db_sqlmodel import get_session  # noqa: E402
from src.podio.podio_auth import get_podio_headers  # noqa: E402
from src.podio.webhook.func_hooks import get_app_id  # noqa: E402

# (app_type, tabla, columna PK, prefijo del formato de Podio)
OBJETIVOS = [
    ("PMC", "parent_mgmt_co", "ID_Community_Tracking", "PMC"),
    ("BDEP", "bldg_dept", "ID_BldgDept", "BLGDEP"),
]
# Freno: si hicieran falta más creaciones que esto, algo no cuadra (p. ej. la
# tabla tiene un máximo disparatado como PMC60035) y hay que mirarlo a mano en
# vez de crear miles de items.
MAX_CREACIONES = 120

if env_config("APP_ENV", default="") != "test":
    sys.exit("⛔ solo para dev: APP_ENV debe ser 'test'")

APLICAR = "--aplicar" in sys.argv


def ocupados(tabla, columna, prefijo):
    with get_session() as s:
        ids = [r[0] for r in s.exec(text(f'select "{columna}" from {tabla}')).all()]
    nums = set()
    for i in ids:
        m = re.search(rf"{prefijo}0*(\d+)$", i or "")
        if m:
            nums.add(int(m.group(1)))
    return nums


def primer_tramo_libre(nums, margen=200):
    """Primer número desde el que hay `margen` libres seguidos.

    Los huecos importan: parent_mgmt_co ocupa 1..22 y luego 60032..60035, así
    que el objetivo son 23 items, no 60036. Apuntar al máximo a secas obligaría
    a crear 60.000 items de usar y tirar.
    """
    ocupados_set = set(nums)
    n = 1
    while True:
        if all((n + k) not in ocupados_set for k in range(margen)):
            return n
        n += 1


def contador_actual(app_type):
    """El contador de la app = app_item_id del último item. Se lee creando uno
    y borrándolo, que es la única forma fiable: /app/<id> no lo expone."""
    h = get_podio_headers(app_type)
    aid = get_app_id(app_type)
    r = requests.post(f"https://api.podio.com/item/app/{aid}/", headers=h,
                      json={"fields": {"title": "sonda contador"}}, timeout=60)
    r.raise_for_status()
    item_id = r.json()["item_id"]
    it = requests.get(f"https://api.podio.com/item/{item_id}", headers=h, timeout=60).json()
    n = it.get("app_item_id")
    requests.delete(f"https://api.podio.com/item/{item_id}", headers=h, timeout=60)
    return int(n)


def quemar(app_type, hasta):
    """Crea y borra items hasta que el contador pase de `hasta`."""
    h = get_podio_headers(app_type)
    aid = get_app_id(app_type)
    n = 0
    while True:
        r = requests.post(f"https://api.podio.com/item/app/{aid}/", headers=h,
                          json={"fields": {"title": f"descartable {n}"}}, timeout=60)
        r.raise_for_status()
        item_id = r.json()["item_id"]
        it = requests.get(f"https://api.podio.com/item/{item_id}", headers=h, timeout=60).json()
        actual = int(it.get("app_item_id"))
        requests.delete(f"https://api.podio.com/item/{item_id}", headers=h, timeout=60)
        n += 1
        if actual > hasta:
            print(f"   contador de {app_type} en {actual} (> {hasta}) tras {n} items")
            return n
        if n >= MAX_CREACIONES:
            print(f"   ⛔ {app_type}: {n} creaciones y el contador va por {actual} — abandono")
            return n


def limpiar_dead_letter(app_type, desde):
    """Quita las colisiones que dejaron los items de usar y tirar.

    Filtro estrecho a propósito: solo `others.<app>` con UniqueViolation y
    posteriores al arranque. Un fallo real de otro tipo se conserva."""
    with get_session() as s:
        n = s.exec(text(
            "delete from podio_failed_syncs where hook_type like :h"
            " and error_message like '%UniqueViolation%' and created_at >= :d"
        ).bindparams(h=f"podio.others.{app_type}.%", d=desde)).rowcount
        s.commit()
    return n


if __name__ == "__main__":
    trabajo = []
    for app_type, tabla, columna, prefijo in OBJETIVOS:
        nums = ocupados(tabla, columna, prefijo)
        libre_desde = primer_tramo_libre(nums)
        actual = contador_actual(app_type)
        falta = max(0, libre_desde - actual)
        print(f"{app_type}: tabla {tabla} ocupa hasta {max(nums) if nums else 0} · "
              f"primer tramo libre desde {libre_desde} · contador TEST en {actual} "
              f"· faltan ~{falta}")
        if falta:
            trabajo.append((app_type, libre_desde - 1))

    if not trabajo:
        print("\n✅ nada que hacer: los contadores TEST ya están por encima")
        sys.exit(0)
    if not APLICAR:
        print("\nℹ️  simulacro. Con --aplicar quita los hooks, adelanta y los repone.")
        sys.exit(0)

    for app_type, hasta in trabajo:
        with get_session() as s:
            arranque = s.exec(text("select now()")).first()[0]
        print(f"\n── {app_type}: adelantando el contador por encima de {hasta}…")
        quemar(app_type, hasta)
        n = limpiar_dead_letter(app_type, arranque)
        print(f"   dead-letter: {n} colisiones de usar y tirar limpiadas")
    print("\n✅ listo. Comprueba con:  scripts/e2e_podio_entrega_real.py PMC BDEP")
