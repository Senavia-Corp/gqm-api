"""Matriz de permisos del sistema de Tasks — auditoría de punta a punta.

Prueba 5 sujetos (Full Admin · GQM Member · Subcontractor · Technical · anónimo)
contra los 7 endpoints de /tasks, sobre 3 objetos (propio · ajeno · inexistente).
Añade dos sondas dirigidas:
  · T-02  /tlactivity protegido con el vocabulario `tasks` y sin scoping
  · T-03  GET /jobs/<id> embebe tareas sin pasar por scope_tasks_statement

Cada intento de ESCRITURA se verifica releyendo la fila en la BD: la respuesta
HTTP no cuenta como prueba. Los conjuntos se ENUMERAN, nunca se cuentan.

Uso:  .venv/bin/python scripts/audit_tasks_matrix.py [--csv ruta.csv]
Sale con código != 0 si algún resultado se desvía de lo esperado.
"""
import csv
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, os.getcwd())

from decouple import config  # noqa: E402
from sqlmodel import select  # noqa: E402

from src.database.db_sqlmodel import get_session  # noqa: E402
from src.models.JobModel import Job  # noqa: E402
from src.models.TasksModel import Tasks  # noqa: E402
from src.models.TLActivityModel import TLActivity  # noqa: E402
from src.models.link_models.JobSubcontractor import JobSubcontractorLink  # noqa: E402
from src.models.link_models.JobTechnician import JobTechnicianLink  # noqa: E402

# ── Guardas de entorno (nunca contra producción) ──────────────────────────────
DB = config("DATABASE_URL", default="")
assert "ep-sparkling-sound" in DB, "⛔ DATABASE_URL no es Neon develop — abortado"
assert config("APP_ENV", default="") == "test", "⛔ APP_ENV != test — abortado"

API = os.environ.get("E2E_API", "http://127.0.0.1:8000").rstrip("/")
PW = config("SEED_DEV_PASSWORD")
NO_EXISTE = "TSK_NO_EXISTE_99999"

FALLOS = []
FILAS = []


def ok(cond, msg):
    print(f"{'OK  ' if cond else 'FAIL'} {msg}", flush=True)
    if not cond:
        FALLOS.append(msg)
    return cond


def call(method, path, token=None, body=None):
    """Devuelve (status, cuerpo). 0 = error de transporte."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200].decode(errors="replace")
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def login(email):
    st, body = call("POST", "/auth/login", body={"Email_Address": email, "Password": PW})
    assert st == 200, f"login {email} → {st}"
    return body["access_token"], body["user_id"]


def ids_de(payload):
    """Enumera ID_Tasks de una respuesta, sea lista o paginada."""
    if payload is None or isinstance(payload, str):
        return set()
    filas = payload if isinstance(payload, list) else payload.get("results", [])
    return {f["ID_Tasks"] for f in filas if isinstance(f, dict) and f.get("ID_Tasks")}


def registra(sujeto, endpoint, objeto, real, esperado, nota=""):
    conforme = real == esperado
    FILAS.append({"sujeto": sujeto, "endpoint": endpoint, "objeto": objeto,
                  "real": real, "esperado": esperado,
                  "conforme": "SI" if conforme else "NO", "nota": nota})
    ok(conforme, f"{sujeto:14s} {endpoint:34s} {objeto:12s} → {real} (esperado {esperado}) {nota}")
    return conforme


# ── Sujetos ───────────────────────────────────────────────────────────────────
print("═══ Sujetos ═══")
SUJ = {}
for rol, email in (("full_admin", "admin-dev@senavia-test.com"),
                   ("gqm_member", "member-dev@senavia-test.com"),
                   ("subcontractor", "sub-dev@senavia-test.com"),
                   ("technical", "tech-dev@senavia-test.com")):
    tok, uid = login(email)
    SUJ[rol] = {"token": tok, "id": uid}
    print(f"  {rol:14s} {uid}")
SUJ["anonimo"] = {"token": None, "id": None}
print("  anonimo        (sin token)")

SUB_ID = SUJ["subcontractor"]["id"]
TEC_ID = SUJ["technical"]["id"]

# ── Mundo de prueba ───────────────────────────────────────────────────────────
sfx = uuid.uuid4().int % 90000 + 10000
J_MIO, J_AJENO = f"QID5{sfx}", f"QID4{sfx}"
T_MIO, T_AJENO = f"TSKM{sfx}", f"TSKA{sfx}"
T_TEC_AJENA = f"TSKX{sfx}"   # tarea del MISMO job pero de otro técnico (sonda T-03)
creadas = []

with get_session() as s:
    s.add(Job(ID_Jobs=J_MIO, Job_type="QID", Project_name="AUDIT del sub"))
    s.add(Job(ID_Jobs=J_AJENO, Job_type="QID", Project_name="AUDIT ajeno"))
    s.add(JobSubcontractorLink(job_id=J_MIO, subcontr_id=SUB_ID))
    s.add(JobTechnicianLink(job_id=J_MIO, technician_id=TEC_ID))
    s.add(Tasks(ID_Tasks=T_MIO, Name="AUDIT mia", ID_Jobs=J_MIO, ID_Technician=TEC_ID))
    s.add(Tasks(ID_Tasks=T_AJENO, Name="AUDIT ajena", ID_Jobs=J_AJENO))
    s.add(Tasks(ID_Tasks=T_TEC_AJENA, Name="AUDIT otro tecnico", ID_Jobs=J_MIO))
    s.commit()
print(f"\nMundo: job propio {J_MIO} · ajeno {J_AJENO} · tareas {T_MIO}/{T_AJENO}/{T_TEC_AJENA}")

try:
    # ══ 1. Anónimo contra los 7 endpoints (regresión ERR-043) ═════════════════
    print("\n═══ 1. Anónimo → los 7 endpoints deben dar 401 ═══")
    for ep, method, path in (
            ("GET /tasks/", "GET", "/tasks/"),
            ("GET /tasks/weekly", "GET", "/tasks/weekly"),
            ("GET /tasks/<id>", "GET", f"/tasks/{T_MIO}"),
            ("GET /tasks/job/<j>/tech/<t>", "GET", f"/tasks/job/{J_MIO}/tech/ALL"),
            ("POST /tasks/", "POST", "/tasks/"),
            ("PATCH /tasks/<id>", "PATCH", f"/tasks/{T_MIO}"),
            ("DELETE /tasks/<id>", "DELETE", f"/tasks/{T_MIO}")):
        st, _ = call(method, path, None, {"Name": "x"} if method in ("POST", "PATCH") else None)
        registra("anonimo", ep, "-", st, 401)

    # ══ 2. Lecturas por rol: enumerar, no contar ══════════════════════════════
    print("\n═══ 2. GET /tasks/ — scoping (enumerando) ═══")
    for rol in ("full_admin", "gqm_member", "subcontractor", "technical"):
        st, body = call("GET", "/tasks/?limit=100", SUJ[rol]["token"])
        vistos = ids_de(body)
        registra(rol, "GET /tasks/", "lista", st, 200)
        if rol in ("subcontractor", "technical"):
            ok(T_AJENO not in vistos,
               f"{rol:14s} NO ve la tarea ajena {T_AJENO} en /tasks/")
        if rol == "technical":
            ok(T_TEC_AJENA not in vistos,
               f"{'technical':14s} NO ve {T_TEC_AJENA} (mismo job, otro técnico)")

    # ══ 3. GET /tasks/<id> — propio · ajeno · inexistente ═════════════════════
    print("\n═══ 3. GET /tasks/<id> ═══")
    for rol in ("full_admin", "gqm_member", "subcontractor", "technical"):
        for etiqueta, tid, esp in (("propio", T_MIO, 200),
                                   ("ajeno", T_AJENO, 200 if rol in ("full_admin", "gqm_member") else 404),
                                   ("inexistente", NO_EXISTE, 404)):
            st, _ = call("GET", f"/tasks/{tid}", SUJ[rol]["token"])
            registra(rol, "GET /tasks/<id>", etiqueta, st, esp)

    # ══ 4. POST /tasks/ — quién puede crear ══════════════════════════════════
    print("\n═══ 4. POST /tasks/ (verificando la fila en BD) ═══")
    for rol, esp_propio in (("full_admin", 201), ("gqm_member", 201),
                            ("subcontractor", 201), ("technical", 403)):
        st, body = call("POST", "/tasks/", SUJ[rol]["token"],
                        {"Name": f"AUDIT {rol}", "ID_Jobs": J_MIO})
        registra(rol, "POST /tasks/", "job propio", st, esp_propio)
        tid = body.get("ID_Tasks") if isinstance(body, dict) else None
        if tid:
            creadas.append(tid)
        with get_session() as s:
            existe = s.exec(select(Tasks).where(Tasks.Name == f"AUDIT {rol}")).first() is not None
        ok(existe == (esp_propio == 201),
           f"{rol:14s} BD: fila {'creada' if existe else 'ausente'} (coherente con {esp_propio})")

        # crear en job AJENO
        esp_ajeno = 201 if rol in ("full_admin", "gqm_member") else 403
        st, body = call("POST", "/tasks/", SUJ[rol]["token"],
                        {"Name": f"AUDIT-IDOR {rol}", "ID_Jobs": J_AJENO})
        registra(rol, "POST /tasks/", "job ajeno", st, esp_ajeno)
        if isinstance(body, dict) and body.get("ID_Tasks"):
            creadas.append(body["ID_Tasks"])

    # ══ 5. PATCH — incluida la reasignación a job ajeno ══════════════════════
    print("\n═══ 5. PATCH /tasks/<id> ═══")
    for rol in ("full_admin", "gqm_member", "subcontractor", "technical"):
        st, _ = call("PATCH", f"/tasks/{T_MIO}", SUJ[rol]["token"], {"Task_status": "Completed"})
        registra(rol, "PATCH /tasks/<id>", "propio", st, 200)
        st, _ = call("PATCH", f"/tasks/{T_AJENO}", SUJ[rol]["token"], {"Task_status": "Completed"})
        registra(rol, "PATCH /tasks/<id>", "ajeno", st,
                 200 if rol in ("full_admin", "gqm_member") else 404)
        # reasignar la tarea propia a un job ajeno → guarda post-update
        if rol in ("subcontractor", "technical"):
            st, _ = call("PATCH", f"/tasks/{T_MIO}", SUJ[rol]["token"], {"ID_Jobs": J_AJENO})
            registra(rol, "PATCH /tasks/<id>", "reasignar", st, 403)
            with get_session() as s:
                fila = s.get(Tasks, T_MIO)
                ok(fila.ID_Jobs == J_MIO,
                   f"{rol:14s} BD: {T_MIO}.ID_Jobs sigue siendo {J_MIO} (no se reasignó)")

    # ══ 6. DELETE — sub y técnico no tienen tasks:delete ═════════════════════
    print("\n═══ 6. DELETE /tasks/<id> ═══")
    for rol in ("subcontractor", "technical"):
        st, _ = call("DELETE", f"/tasks/{T_MIO}", SUJ[rol]["token"])
        registra(rol, "DELETE /tasks/<id>", "propio", st, 403)
        with get_session() as s:
            ok(s.get(Tasks, T_MIO) is not None,
               f"{rol:14s} BD: {T_MIO} sigue existiendo tras el DELETE denegado")
    for rol in ("full_admin", "gqm_member"):
        st, _ = call("DELETE", f"/tasks/{NO_EXISTE}", SUJ[rol]["token"])
        registra(rol, "DELETE /tasks/<id>", "inexistente", st, 404)

    # ══ 7. T-03 · /jobs/<id> vs /tasks/ con el MISMO token ═══════════════════
    print("\n═══ 7. T-03 · ¿el embebido de /jobs/<id> respeta el scoping? ═══")
    for rol in ("subcontractor", "technical"):
        tok = SUJ[rol]["token"]
        _, jb = call("GET", f"/jobs/{J_MIO}", tok)
        via_job = {t["ID_Tasks"] for t in (jb.get("tasks") or [])} if isinstance(jb, dict) else set()
        _, tl = call("GET", "/tasks/?limit=100", tok)
        via_tasks = ids_de(tl)
        fuga = via_job - via_tasks
        print(f"  {rol}: /jobs/{J_MIO}.tasks = {sorted(via_job)}")
        print(f"  {rol}: /tasks/ (del mismo job) = {sorted(via_tasks & via_job | (via_job & via_tasks))}")
        ok(not fuga,
           f"{rol:14s} T-03: /jobs/<id> no expone tareas que /tasks/ oculta "
           f"{'— FUGA: ' + str(sorted(fuga)) if fuga else ''}")
        registra(rol, "GET /jobs/<id>.tasks", "fuga", len(fuga), 0,
                 f"fugadas={sorted(fuga)}" if fuga else "")

    # ══ 8. T-02 · /tlactivity con vocabulario `tasks` y sin scoping ══════════
    print("\n═══ 8. T-02 · /tlactivity (auditoría) por rol ═══")
    with get_session() as s:
        muestra = s.exec(select(TLActivity)).first()
    tla_id = muestra.ID_TLActivity if muestra else None
    print(f"  fila de muestra: {tla_id}")

    for rol in ("full_admin", "gqm_member", "subcontractor", "technical"):
        tok = SUJ[rol]["token"]
        portal = rol in ("subcontractor", "technical")

        st, body = call("GET", "/tlactivity/?limit=5", tok)
        registra(rol, "GET /tlactivity/", "log completo", st, 403 if portal else 200,
                 "⚠ FUGA: lee el log entero" if portal and st == 200 else "")

        st, body = call("POST", "/tlactivity/", tok,
                        {"Action": "AUDIT falsificada", "Description": f"inyectada por {rol}"})
        forjada = body.get("ID_TLActivity") if isinstance(body, dict) else None
        registra(rol, "POST /tlactivity/", "fabricar", st, 403 if portal else 201,
                 "⚠ FABRICÓ auditoría" if portal and st in (200, 201) else "")
        if forjada:
            with get_session() as s:
                fila = s.get(TLActivity, forjada)
                if fila:
                    ok(not portal,
                       f"{rol:14s} BD: entrada falsificada {forjada} PERSISTIDA en tlactivity")
                    s.delete(fila)
                    s.commit()

        if tla_id:
            st, _ = call("PATCH", f"/tlactivity/{tla_id}", tok, {"Description": "AUDIT alterada"})
            registra(rol, "PATCH /tlactivity/<id>", "alterar", st, 403 if portal else 200,
                     "⚠ ALTERÓ auditoría" if portal and st == 200 else "")
            st, _ = call("DELETE", f"/tlactivity/{NO_EXISTE}", tok)
            registra(rol, "DELETE /tlactivity/<id>", "inexistente", st, 403 if portal else 404)

    # ══ 9. T-01 · ¿deja rastro útil la auditoría de tasks? ═══════════════════
    print("\n═══ 9. T-01 · rastro de auditoría de una creación real ═══")
    st, body = call("POST", "/tasks/", SUJ["full_admin"]["token"],
                    {"Name": "AUDIT rastro", "ID_Jobs": J_MIO})
    tid = body.get("ID_Tasks") if isinstance(body, dict) else None
    if tid:
        creadas.append(tid)
        with get_session() as s:
            ev = s.exec(select(TLActivity).where(TLActivity.Action == "Task created")
                        .order_by(TLActivity.Action_datetime.desc())).first()
        if ev:
            print(f"  último 'Task created': ID_Jobs={ev.ID_Jobs!r} "
                  f"Description={ev.Description!r} ID_Member={ev.ID_Member!r}")
            ok(ev.ID_Jobs == J_MIO,
               f"T-01: el evento cuelga del job {J_MIO} (real: {ev.ID_Jobs!r})")
        else:
            ok(False, "T-01: no se escribió ninguna fila 'Task created'")

finally:
    # ── Limpieza ─────────────────────────────────────────────────────────────
    print("\n═══ Limpieza ═══")
    with get_session() as s:
        for tid in set(creadas) | {T_MIO, T_AJENO, T_TEC_AJENA}:
            fila = s.get(Tasks, tid)
            if fila:
                s.delete(fila)
        for fila in s.exec(select(Tasks).where(Tasks.Name.like("AUDIT%"))).all():
            s.delete(fila)
        for modelo, jid in ((JobSubcontractorLink, J_MIO), (JobTechnicianLink, J_MIO)):
            for fila in s.exec(select(modelo).where(modelo.job_id == jid)).all():
                s.delete(fila)
        for jid in (J_MIO, J_AJENO):
            fila = s.exec(select(Job).where(Job.ID_Jobs == jid)).first()
            if fila:
                s.delete(fila)
        for fila in s.exec(select(TLActivity).where(
                TLActivity.Action == "AUDIT falsificada")).all():
            s.delete(fila)
        s.commit()
    print("  mundo de prueba eliminado")

    if "--csv" in sys.argv:
        ruta = sys.argv[sys.argv.index("--csv") + 1]
        with open(ruta, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(FILAS[0].keys()))
            w.writeheader()
            w.writerows(FILAS)
        print(f"  CSV → {ruta} ({len(FILAS)} filas)")

    print(f"\n{'='*70}\n{len(FILAS)} comprobaciones · {len(FALLOS)} desviaciones")
    for f in FALLOS:
        print(f"  ✗ {f}")

sys.exit(1 if FALLOS else 0)
