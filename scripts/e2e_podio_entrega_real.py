"""Criterio de ENTREGA REAL: escribe Podio, espera la BD. Sin simular el hook.

`e2e_podio_sync.py` publica el payload del webhook ÉL MISMO. Eso prueba el
RECEPTOR, no la ENTREGA: pasa en verde aunque el hook esté mal registrado, mal
autenticado o no exista. Y eso es exactamente lo que pasó — Podio descarta el
query string, así que todas sus entregas respondían 403 durante días y el arnés
seguía marcando 42/42.

Este script no toca el receptor. Escribe en la app de Podio por su propia API y
espera a que la fila aparezca / cambie / desaparezca en Neon develop. El único
camino entre las dos cosas es el webhook registrado en Podio. Si el hook no
entrega, esto falla.

Cubre las TRES rutas de recepción y las 7 apps: cada una tiene su propio
mapper y su propio procesador, así que rompen por separado.
  /webhook/podio/jobs/<tipo>/<año>          QID · PTL · PAR
  /webhook/podio/others/relations/<app>     CLI · SUBC
  /webhook/podio/others/no_relations/<app>  PMC · BDEP

Uso:  .venv/bin/python scripts/e2e_podio_entrega_real.py [QID PTL PAR CLI SUBC PMC BDEP]
Exit != 0 si algo no llega.
"""
import os
import sys
import time

sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/gqm-api-fixes"))
os.chdir(os.path.expanduser("~/Documents/GitHub/gqm-api-fixes"))

import requests  # noqa: E402
from sqlmodel import select  # noqa: E402

from src.database.db_sqlmodel import get_session  # noqa: E402
from src.models.BldgDeptModel import BuildingDept  # noqa: E402
from src.models.ClientModel import Client  # noqa: E402
from src.models.JobModel import Job  # noqa: E402
from src.models.ParentMgmtCoModel import ParentMgmtCo  # noqa: E402
from src.models.SubcontractorModel import Subcontractor  # noqa: E402
from src.podio.podio_auth import get_podio_headers  # noqa: E402
from src.podio.services.job_services import podio_jobs_router  # noqa: E402
from src.podio.webhook.func_hooks import get_app_id  # noqa: E402

YEAR = 2026
# Cuánto le damos a Podio para entregar. Sus hooks no son instantáneos y el
# arranque en frío de la lambda suma; 90 s es holgado y aun así falla rápido
# cuando el hook está mal, porque entonces no llega NUNCA.
TIMEOUT = 90
PASO = 3

# (modelo, campo del modelo con el texto, external_id en Podio)
# El campo de texto es distinto por app: PTL y PAR no modelan nombre de
# proyecto (su título es 'Property ID' y 'RES/IND').
CASOS = {
    "QID":  (Job, "Project_name", "project-name-2"),
    "PTL":  (Job, "Ptl_property_id", "title"),
    "PAR":  (Job, "Po_wtn_wo", "payment-date-and-number-1"),
    "CLI":  (Client, "Client_Community", "title"),
    # SUBC no tiene campo 'title': su nombre es 'name' y 'organization' es tag.
    "SUBC": (Subcontractor, "Name", "name"),
    "PMC":  (ParentMgmtCo, "Property_mgmt_co", "title"),
    "BDEP": (BuildingDept, "City_BldgDept", "title"),
}
JOB_TYPES = {"QID", "PTL", "PAR"}

FALLOS = []


def ok(cond, msg):
    print(f"{'OK  ' if cond else 'FAIL'} {msg}", flush=True)
    if not cond:
        FALLOS.append(msg)
    return cond


def esperar(msg, comprueba):
    """Espera a que la BD cumpla la condición. Sesión nueva en cada vuelta:
    reutilizar la sesión devuelve el snapshot viejo y esto pasaría en verde
    sin que hubiera llegado nada."""
    limite = time.time() + TIMEOUT
    while True:
        with get_session() as s:
            valor = comprueba(s)
        if valor:
            t = int(TIMEOUT - (limite - time.time()))
            return ok(True, f"{msg} (llegó en ~{t}s)")
        if time.time() >= limite:
            return ok(False, f"{msg} — NO LLEGÓ en {TIMEOUT}s")
        time.sleep(PASO)


# --- escritura en Podio: por su API, nunca por la nuestra ----------------

def _campos_obligatorios(app_type):
    """Las apps tienen categorías required (CLI: 'Compliance Partner'). Sin
    rellenarlas Podio rechaza el create con 400."""
    aid = get_app_id(app_type)
    r = requests.get(f"https://api.podio.com/app/{aid}",
                     headers=get_podio_headers(app_type), timeout=30)
    r.raise_for_status()
    extra = {}
    for f in r.json().get("fields", []):
        cfg = f.get("config") or {}
        if not cfg.get("required") or f.get("external_id") == "title":
            continue
        if f.get("type") == "category":
            opciones = (cfg.get("settings") or {}).get("options") or []
            if opciones:
                extra[f["external_id"]] = opciones[0]["id"]
    return extra


class PodioApp:
    """create/update/delete contra la app real, sea de Jobs o estática."""

    def __init__(self, app_type):
        self.app_type = app_type
        if app_type in JOB_TYPES:
            self.svc = podio_jobs_router.get_service(job_type=app_type, year=YEAR)
        else:
            self.svc = None
            self.app_id = get_app_id(app_type)

    def _h(self):
        return get_podio_headers(self.app_type)

    def crear(self, campos):
        if self.svc:
            return self.svc.create_item(campos).get("item_id")
        r = requests.post(f"https://api.podio.com/item/app/{self.app_id}/",
                          headers=self._h(), json={"fields": campos}, timeout=60)
        r.raise_for_status()
        return r.json().get("item_id")

    def actualizar(self, item_id, campos):
        if self.svc:
            return self.svc.update_item(int(item_id), campos)
        r = requests.put(f"https://api.podio.com/item/{item_id}",
                         headers=self._h(), json={"fields": campos}, timeout=60)
        r.raise_for_status()

    def borrar(self, item_id):
        if self.svc:
            return self.svc.delete_item(int(item_id))
        r = requests.delete(f"https://api.podio.com/item/{item_id}",
                            headers=self._h(), timeout=60)
        r.raise_for_status()


def ciclo(app_type):
    Model, attr, slug = CASOS[app_type]
    app = PodioApp(app_type)
    marca = f"ENTREGA {app_type} {int(time.time())}"
    print(f"\n=== {app_type} — entrega real (Podio dispara) ===", flush=True)

    campos = {slug: marca}
    if app_type not in JOB_TYPES:
        campos.update(_campos_obligatorios(app_type))

    item_id = app.crear(campos)
    if not ok(bool(item_id), f"[{app_type}] item creado en Podio TEST: {item_id}"):
        return

    try:
        esperar(
            f"[{app_type}] item.create entregado → fila en la BD",
            lambda s: s.exec(select(Model).where(
                Model.podio_item_id == str(item_id))).first() is not None)

        nuevo = f"{marca} EDITADO"
        app.actualizar(item_id, {slug: nuevo})
        esperar(
            f"[{app_type}] item.update entregado → {attr} = '...EDITADO'",
            lambda s: getattr(s.exec(select(Model).where(
                Model.podio_item_id == str(item_id))).first(), attr, None) == nuevo)
    finally:
        app.borrar(item_id)

    esperar(
        f"[{app_type}] item.delete entregado → fila fuera de la BD",
        lambda s: s.exec(select(Model).where(
            Model.podio_item_id == str(item_id))).first() is None)


if __name__ == "__main__":
    pedidos = [a.upper() for a in sys.argv[1:]] or list(CASOS)
    for app_type in pedidos:
        if app_type not in CASOS:
            FALLOS.append(f"app_type desconocido: {app_type}")
            continue
        try:
            ciclo(app_type)
        except Exception as e:  # el fallo se reporta, no aborta el resto
            ok(False, f"[{app_type}] excepción: {type(e).__name__}: {str(e)[:200]}")

    print("\n" + "=" * 60)
    if FALLOS:
        print(f"⛔ {len(FALLOS)} FALLOS:")
        for f in FALLOS:
            print("   -", f)
        sys.exit(1)
    print(f"✅ Podio entrega de verdad en: {', '.join(pedidos)}")
