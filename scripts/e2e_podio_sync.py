"""E2E REAL: ciclo crear/editar/borrar en AMBOS sentidos contra las apps
Podio TEST. Sin mocks. Exit != 0 si algo falla."""
import os
import sys
import time

sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/gqm-api-fixes"))
os.chdir(os.path.expanduser("~/Documents/GitHub/gqm-api-fixes"))

import requests  # noqa: E402
from decouple import config  # noqa: E402
from sqlmodel import select  # noqa: E402

from src.database.db_sqlmodel import get_session  # noqa: E402
from src.models.JobModel import Job  # noqa: E402
from src.podio.services.job_services import podio_jobs_router  # noqa: E402

# Por defecto la pila local; para validar el entorno desplegado (el criterio
# de aceptación antes de que lo pruebe el cliente):
#   E2E_API=https://<api-desplegado> python scripts/e2e_podio_sync.py
API = os.environ.get("E2E_API", "http://localhost:8000").rstrip("/")
# Campo de texto que va y vuelve, por tipo. VERIFICADO contra el esquema real
# de las apps TEST (no asumido): PTL y PAR NO tienen campo de nombre de
# proyecto — su 'title' es 'Property ID' y 'RES/IND' respectivamente — así que
# el round-trip se prueba con el campo que cada app sí modela.
#   (campo del modelo, external_id en Podio)
RT = {
    "QID": ("Project_name",    "project-name-2"),
    "PTL": ("Ptl_property_id", "title"),
    "PAR": ("Po_wtn_wo",       "payment-date-and-number-1"),
}
YEAR = 2026
FAILS = []


def ok(cond, msg):
    print(f"{'OK  ' if cond else 'FAIL'} {msg}", flush=True)
    if not cond:
        FAILS.append(msg)
    return cond


def login():
    r = requests.post(f"{API}/auth/login", json={
        "Email_Address": "admin-dev@senavia-test.com",
        "Password": config("SEED_DEV_PASSWORD")}, timeout=30)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def podio_item(job_type, item_id):
    svc = podio_jobs_router.get_service(job_type=job_type, year=YEAR)
    try:
        return svc.get_item(int(item_id))
    except Exception as e:
        if any(c in str(e) for c in ("404", "403", "410", "not found", "Not found")):
            return None
        raise


def field_text(item, external_id):
    for f in (item or {}).get("fields", []):
        if f.get("external_id") == external_id:
            vals = f.get("values") or []
            if vals:
                return vals[0].get("value")
    return None


def ciclo(H, job_type):
    print(f"\n=== {job_type} — outbound (app → Podio) ===", flush=True)
    attr, slug = RT[job_type]
    name = f"E2E {job_type} {int(time.time())}"

    r = requests.post(f"{API}/jobs/?sync_podio=true&year={YEAR}", headers=H,
                      json={"Job_type": job_type, attr: name}, timeout=120)
    if not ok(r.status_code < 300, f"[{job_type}] POST /jobs con sync → {r.status_code}"):
        print(f"     {r.text[:300]}")
        return
    job = r.json()
    job_id, item_id = job.get("ID_Jobs"), job.get("podio_item_id")
    ok(bool(item_id), f"[{job_type}] job {job_id} nació con podio_item_id={item_id}")
    if not item_id:
        return

    with get_session() as s:
        row = s.exec(select(Job).where(Job.ID_Jobs == job_id)).first()
        ok(row is not None and str(row.podio_app_year) == str(YEAR),
           f"[{job_type}] podio_app_year persistido = {getattr(row, 'podio_app_year', None)}")

    item = podio_item(job_type, item_id)
    ok(item is not None, f"[{job_type}] item {item_id} EXISTE en la app TEST")
    ok(field_text(item, slug) == name,
       f"[{job_type}] {attr} viajó a Podio → {slug}")

    nuevo = f"{name} EDITADO"
    r = requests.patch(f"{API}/jobs/{job_id}?sync_podio=true&year={YEAR}", headers=H,
                       json={attr: nuevo}, timeout=120)
    ok(r.status_code < 300, f"[{job_type}] PATCH /jobs con sync → {r.status_code}")
    if r.status_code >= 300:
        print(f"     {r.text[:300]}")
    time.sleep(2)
    item = podio_item(job_type, item_id)
    ok(item is not None and field_text(item, slug) == nuevo,
       f"[{job_type}] la edición se reflejó en Podio ({slug})")

    r = requests.delete(f"{API}/jobs/{job_id}?sync_podio=true&year={YEAR}&force=true",
                        headers=H, timeout=120)
    ok(r.status_code < 300, f"[{job_type}] DELETE /jobs con sync → {r.status_code}")
    if r.status_code >= 300:
        print(f"     {r.text[:300]}")
    time.sleep(2)
    ok(podio_item(job_type, item_id) is None,
       f"[{job_type}] item {item_id} BORRADO de la app TEST")
    with get_session() as s:
        ok(s.exec(select(Job).where(Job.ID_Jobs == job_id)).first() is None,
           f"[{job_type}] job {job_id} fuera de la BD")


def inbound(H, job_type):
    print(f"\n=== {job_type} — inbound (Podio → app) ===", flush=True)
    svc = podio_jobs_router.get_service(job_type=job_type, year=YEAR)
    attr, slug = RT[job_type]
    name = f"E2E {job_type} in {int(time.time())}"
    created = svc.create_item({slug: name})
    item_id = created.get("item_id")
    ok(bool(item_id), f"[{job_type}] item creado en Podio TEST: {item_id}")
    if not item_id:
        return
    token = config("PODIO_WEBHOOK_TOKEN", default="")
    url = f"{API}/webhook/podio/jobs/{job_type}/{YEAR}?token={token}"
    try:
        r = requests.post(url, json={"type": "item.create", "item_id": item_id}, timeout=120)
        ok(r.status_code == 200, f"[{job_type}] webhook item.create → {r.status_code}")
        if r.status_code != 200:
            print(f"     {r.text[:300]}")
        time.sleep(1)
        with get_session() as s:
            row = s.exec(select(Job).where(Job.podio_item_id == str(item_id))).first()
            ok(row is not None, f"[{job_type}] job creado en la app desde Podio: "
                                f"{row.ID_Jobs if row else None}")

        svc.update_item(int(item_id), {slug: f"{name} EDITADO"})
        r = requests.post(url, json={"type": "item.update", "item_id": item_id}, timeout=120)
        ok(r.status_code == 200, f"[{job_type}] webhook item.update → {r.status_code}")
        time.sleep(1)
        with get_session() as s:
            row = s.exec(select(Job).where(Job.podio_item_id == str(item_id))).first()
            got = getattr(row, attr, None) if row else None
            ok(row is not None and "EDITADO" in (str(got or "")),
               f"[{job_type}] la edición entrante llegó a la app ({attr}={got})")

        svc.delete_item(int(item_id))
        r = requests.post(url, json={"type": "item.delete", "item_id": item_id}, timeout=120)
        ok(r.status_code == 200, f"[{job_type}] webhook item.delete → {r.status_code}")
        with get_session() as s:
            ok(s.exec(select(Job).where(Job.podio_item_id == str(item_id))).first() is None,
               f"[{job_type}] job borrado en la app desde Podio")
    finally:
        if podio_item(job_type, item_id) is not None:
            try:
                svc.delete_item(int(item_id))
            except Exception:
                pass


def main():
    assert "ep-sparkling-sound" in config("DATABASE_URL", default=""), "no es develop"
    assert config("APP_ENV", default="") == "test", "APP_ENV != test"
    H = login()
    # Conteo de partida: lo que importa es que el ciclo no AÑADA entradas
    base = requests.get(f"{API}/webhook/podio/failed_syncs/count",
                        headers=H, timeout=30).json().get("count", 0)
    print(f"dead-letter al empezar: {base}")
    for jt in ("QID", "PTL", "PAR"):
        ciclo(H, jt)
        inbound(H, jt)

    r = requests.get(f"{API}/webhook/podio/failed_syncs/count", headers=H, timeout=30)
    n = r.json().get("count")
    # Las apps TEST tienen los hooks apuntando al VPS (api.taskipos.com) sobre
    # la MISMA BD develop: cada item que creamos lo procesa también el VPS y
    # choca por clave duplicada. Es ruido de entorno, no de nuestro código, así
    # que se informa aparte en vez de fallar.
    ajenas = requests.get(f"{API}/webhook/podio/failed_syncs", headers=H,
                          timeout=30).json()
    carrera = [f for f in ajenas if not f.get("resolved")
               and "duplicate key" in (f.get("error_message") or "")]
    propias = n - len(carrera)
    if carrera:
        print(f"ℹ️  {len(carrera)} entrada(s) por la carrera con el VPS "
              f"(hooks duplicados en las apps TEST) — ruido de entorno")
    ok(propias <= base,
       f"el ciclo no añadió fallos propios a la dead-letter (propias={propias}, base={base})")

    print(f"\n{'='*60}\n{'TODO EN VERDE' if not FAILS else f'{len(FAILS)} FALLOS'}")
    for f in FAILS:
        print(f"  - {f}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
