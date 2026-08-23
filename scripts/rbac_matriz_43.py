"""Tabla §4.3 del encargo RBAC: 4 roles × comprobaciones por API, con los tokens de
~/.gqm-rbac-tokens/ (ver rbac_tokens.py). Esperado = la SPEC (no el comportamiento actual).

  --api URL            defecto http://127.0.0.1:8000
  --entorno dev|prod   dev: resuelve ids/conteos contra la BD del .env (develop) y ejecuta
                       DELETE sobre ids inexistentes; prod: exige --sin-bd + ids/totales por
                       argv y NUNCA ejecuta un DELETE con un rol que pueda (R3)
  --md RUTA            escribe la tabla Markdown
  --totales jobs=N,tasks=N         (prod)   --job-ajeno ID --sub-ajeno ID --member-ajeno ID
  --pmc-ajeno ID  --status "Texto" (prod)   --job-propio ID --task-propia ID (dev: se resuelven)
Salida ≠0 si hay ❌. Nunca imprime tokens.
"""
import json, os, pathlib, ssl, sys, urllib.error, urllib.request

ROLES = ["FULL_ADMIN", "GQM_MEMBER", "SUBCONTRACTOR", "TECHNICAL"]
SHORT = {"FULL_ADMIN": "FA", "GQM_MEMBER": "GM", "SUBCONTRACTOR": "SUB", "TECHNICAL": "TEC"}
TOK_DIR = pathlib.Path.home() / ".gqm-rbac-tokens"
argv = sys.argv[1:]


def arg(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


API = arg("--api", "http://127.0.0.1:8000").rstrip("/")
ENT = arg("--entorno", "dev")
SIN_BD = "--sin-bd" in argv or ENT == "prod"
if ENT == "prod" and "--sin-bd" not in argv:
    sys.exit("⛔ en prod exige --sin-bd")


def _ssl():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def call(method, path, token, body=None):
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(API + path, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120, context=_ssl()) as r:
            raw = r.read()
            ctype = r.headers.get("Content-Type", "")
            if "json" in ctype:
                return r.status, json.loads(raw) if raw else None
            return r.status, {"_bytes": len(raw)}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"_raw": raw[:120].decode(errors="replace")}
    except Exception as e:  # noqa: BLE001
        return 0, {"_error": str(e)}


tokens = {}
for r in ROLES:
    p = TOK_DIR / f"{r}.json"
    if not p.exists():
        sys.exit(f"⛔ falta {p} (ejecuta rbac_tokens.py)")
    tokens[r] = json.load(open(p))

ids = {
    "sub": tokens["SUBCONTRACTOR"]["user_id"], "tec": tokens["TECHNICAL"]["user_id"],
    "gm": tokens["GQM_MEMBER"]["user_id"], "fa": tokens["FULL_ADMIN"]["user_id"],
    "job_propio": arg("--job-propio"), "job_ajeno": arg("--job-ajeno"), "sub_ajeno": arg("--sub-ajeno"),
    "member_ajeno": arg("--member-ajeno"), "pmc_ajeno": arg("--pmc-ajeno"), "task_propia": arg("--task-propia"),
    "status": arg("--status"),
}
tot = {"jobs": None, "tasks": None}
own = {"jobs_sub": set(), "jobs_tec": set(), "tasks_sub": None, "tasks_tec": None}
if arg("--totales"):
    for kv in arg("--totales").split(","):
        k, v = kv.split("=")
        tot[k] = int(v)

if not SIN_BD:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from sqlalchemy import text
    from src.database.db_sqlmodel import get_session
    with get_session() as s:
        q = lambda sql: [tuple(r) for r in s.exec(text(sql))]  # noqa: E731
        own["jobs_sub"] = {r[0] for r in q(f"select job_id from job_subcontractor where subcontr_id='{ids['sub']}'")}
        own["jobs_tec"] = {r[0] for r in q(f"select job_id from job_technician where technician_id='{ids['tec']}'")}
        tot["jobs"] = q("select count(*) from jobs")[0][0]
        tot["tasks"] = q("select count(*) from tasks")[0][0]
        own["tasks_tec"] = q(f"select count(*) from tasks where \"ID_Technician\"='{ids['tec']}'")[0][0]
        own["tasks_sub"] = q(f"""select count(*) from tasks where "ID_Subcontractor"='{ids['sub']}'
            or "ID_Jobs" in (select job_id from job_subcontractor where subcontr_id='{ids['sub']}')""")[0][0]
        ids["job_propio"] = ids["job_propio"] or sorted(own["jobs_sub"])[0]
        ids["job_ajeno"] = ids["job_ajeno"] or q(f"""select "ID_Jobs" from jobs where "ID_Jobs" not in
            (select job_id from job_subcontractor where subcontr_id='{ids['sub']}') and "ID_Client" is not null limit 1""")[0][0]
        ids["sub_ajeno"] = ids["sub_ajeno"] or q(f"select subcontr_id from job_subcontractor where subcontr_id<>'{ids['sub']}' limit 1")[0][0]
        ids["member_ajeno"] = ids["member_ajeno"] or q(f"select \"ID_Member\" from member where \"ID_Member\" not in ('{ids['gm']}','{ids['fa']}') limit 1")[0][0]
        ids["pmc_ajeno"] = ids["pmc_ajeno"] or q(f"""select c."ID_Community_Tracking" from jobs j join client c on c."ID_Client"=j."ID_Client"
            where j."ID_Jobs"='{ids['job_ajeno']}'""")[0][0]
        ids["task_propia"] = ids["task_propia"] or q(f"select \"ID_Tasks\" from tasks where \"ID_Technician\"='{ids['tec']}' limit 1")[0][0]
        ids["status"] = ids["status"] or q(f"select \"Job_status\" from jobs where \"ID_Jobs\"='{ids['job_propio']}'")[0][0]
        ids["client_propio"] = q(f"select \"ID_Client\" from jobs where \"ID_Jobs\"='{ids['job_propio']}'")[0][0]
        tot["status"] = q(f"select count(*) from jobs where \"Job_status\"='{ids['status']}'")[0][0]
else:
    for k in ("job_ajeno", "sub_ajeno", "member_ajeno", "pmc_ajeno", "status"):
        if not ids[k]:
            sys.exit(f"⛔ prod: falta --{k.replace('_', '-')}")
    ids["client_propio"] = None

PROD = ENT == "prod"
R3 = "R3"          # no ejecutado: el rol podría borrar de verdad
OK = object()      # cualquier código que no sea 401/403


def n_of(body):
    if isinstance(body, dict):
        if "total" in body:
            return body["total"]
        if isinstance(body.get("results"), list):
            return len(body["results"])
        if isinstance(body.get("data"), list):
            return len(body["data"])
    if isinstance(body, list):
        return len(body)
    return None


def items_of(body):
    if isinstance(body, dict):
        for k in ("results", "data", "jobs"):
            if isinstance(body.get(k), list):
                return body[k]
        return [body] if "ID_Jobs" in body else []
    return body if isinstance(body, list) else []


def jp(): return ids["job_propio"]
def ja(): return ids["job_ajeno"]


# esperado por rol: int | tupla de ints | OK | R3 | dict(status=, n=|subset=|sin=|can=|nota=) | None (saltar)
def fila(grupo, metodo, ruta, cuerpo, fa, gm, sub, tec):
    return (grupo, metodo, ruta, cuerpo, {"FULL_ADMIN": fa, "GQM_MEMBER": gm, "SUBCONTRACTOR": sub, "TECHNICAL": tec})


BASICS = dict(status=200, sin="Gqm_formula_pricing")
own_or_skip = None if PROD else 200
del_fa = R3 if PROD else 404
FILAS = [
    fila("JOBS", "GET", "/jobs/?limit=100", None, dict(status=200, n="jobs"), dict(status=200, n="jobs"),
         dict(status=200, n="jobs_sub"), dict(status=200, n="jobs_tec", sin="Gqm_formula_pricing")),
    fila("JOBS", "GET", "/jobs/jobs_table?limit=100", None, dict(status=200, n="jobs"), dict(status=200, n="jobs"),
         dict(status=200, n="jobs_sub"), dict(status=200, n="jobs_tec", sin="Gqm_formula_pricing")),
    # En prod el sub de prueba tiene 0 jobs: no hay «job propio» que pedir (se omite la fila entera).
    fila("JOBS", "GET", lambda: f"/jobs/{jp()}", None, None if PROD else 200, None if PROD else 200,
         own_or_skip, None if PROD else BASICS),
    fila("JOBS", "GET", lambda: f"/jobs/{ja()}", None, 200, 200, 404, 404),
    fila("JOBS", "GET", "/jobs/by-type-year?type=QID&year=2026&limit=100", None, 200, 200,
         dict(status=200, subset="jobs_sub"), dict(status=200, subset="jobs_tec", sin="Gqm_formula_pricing")),
    fila("JOBS", "GET", lambda: f"/jobs/oldest?parent_mgmt_co_id={ids['pmc_ajeno']}", None, 200, 200, 404, 404),
    # OJO: en Vercel el path llega SIN decodificar, así que un status con espacios
    # ("Completed PVI") no casa en la BD y la ruta devuelve 200 con lista vacía. Es
    # anterior a esta entrega y ninguna pantalla usa la ruta; en prod solo se afirma
    # el 200 (autorización), no el conteo.
    fila("JOBS", "GET", lambda: f"/jobs/status/{urllib.request.quote(ids['status'])}?limit=100", None,
         dict(status=200, nota="⚠ conteo omitido en prod: path codificado") if PROD else dict(status=200, n="status"),
         dict(status=200, nota="⚠ conteo omitido en prod: path codificado") if PROD else dict(status=200, n="status"),
         dict(status=200, subset="jobs_sub"), dict(status=200, subset="jobs_tec", sin="Gqm_formula_pricing")),
    # /type y /member cargan TODO el resultado en memoria (sin LIMIT en BD): en prod solo
    # se miden con los roles de portal (scoped → pocas filas); para staff se omiten.
    fila("JOBS", "GET", "/jobs/type/QID?limit=100", None, None if PROD else 200, None if PROD else 200,
         dict(status=200, subset="jobs_sub"), dict(status=200, subset="jobs_tec", sin="Gqm_formula_pricing")),
    fila("JOBS", "GET", lambda: f"/jobs/subcontractor/{ids['sub_ajeno']}", None, 200, 200, 403, 403),
    fila("JOBS", "GET", lambda: f"/jobs/subcontractor/{ids['sub']}", None, 200, 200, dict(status=200, subset="jobs_sub"), 403),
    fila("JOBS", "GET", lambda: f"/jobs/member/{ids['member_ajeno']}?limit=100", None,
         None if PROD else 200, None if PROD else 200,
         dict(status=200, subset="jobs_sub"), dict(status=200, subset="jobs_tec", sin="Gqm_formula_pricing")),
    fila("JOBS", "POST", "/jobs/", {}, (400, 422), (400, 422), 403, 403),
    fila("JOBS", "PATCH", "/jobs/ZZNOEXISTE", {}, (400, 404, 422), (400, 404, 422), 403, 403),
    fila("JOBS", "DELETE", "/jobs/ZZNOEXISTE", None, del_fa, 403, 403, 403),
    fila("JOBS", "POST", "/jobs_excel/export", {"filters": {"statuses": ["ZZ-NINGUNO"]}}, 200, 200, 200, 403),
    fila("MIEMBROS", "GET", "/member/?limit=10", None, 200, dict(status=200, sin="Email_Address"), 403, 403),
    fila("MIEMBROS", "GET", "/member/member_table?limit=10", None, 200, dict(status=200, sin="Email_Address"), 403, 403),
    fila("MIEMBROS", "GET", lambda: f"/member/{ids['gm']}", None, 200, 200, 403, 403),
    fila("MIEMBROS", "GET", lambda: f"/member/{ids['member_ajeno']}", None, 200, 403, 403, 403),
    fila("MIEMBROS", "POST", "/member/", {}, (400, 422), 403, 403, 403),
    fila("ROLES/PERM", "GET", "/role/", None, 200, 200, 403, 403),
    fila("ROLES/PERM", "GET", "/permission/", None, 200, 200, 403, 403),
    fila("ROLES/PERM", "POST", "/role/", {}, (400, 422), 403, 403, 403),
    fila("ROLES/PERM", "POST", "/permission_role/permission/PERM-NO/role/ROL-NO", None, 404, 403, 403, 403),
    fila("COMISIONES", "GET", "/commission/?limit=10", None, 200, 403, 403, 403),
    fila("COMISIONES", "GET", "/commission/commission_table?limit=10", None, 200, 403, 403, 403),
    fila("COMISIONES", "GET", lambda: f"/commission/member/{ids['gm']}", None, 200, 403, 403, 403),
    fila("COMISIONES", "GET", lambda: f"/commission/member/{ids['member_ajeno']}", None, 200, 403, 403, 403),
    fila("COMISIONES", "PATCH", "/commission/ZZNOEXISTE", {}, (400, 404, 422), 403, 403, 403),
    fila("MULTIPLIC.", "GET", "/multiplier/", None, 200, 200, 403, 403),
    fila("MULTIPLIC.", "POST", "/multiplier/", {"Multiplier": "x"}, dict(status=500, nota="⚠ 500 en validación (bug previo, no crea fila)"), 403, 403, 403),
    fila("MULTIPLIC.", "POST", "/job_multiplier/jobs/J-NO/multipliers/M-NO", None, 404, 403, 403, 403),
    fila("MULTIPLIC.", "DELETE", "/job_member/jobs/J-NO/members/M-NO", None, del_fa, R3 if PROD else 404, 403, 403),
    fila("TÉCNICOS", "GET", "/technician/?limit=10", None, 200, 200, dict(status=200, nota="⚠ sin scoping, Fase B"),
         dict(status=200, nota="⚠ sin scoping, Fase B")),
    fila("TÉCNICOS", "POST", "/technician/", {}, (400, 422), (400, 422), 403, 403),
    fila("TÉCNICOS", "POST", "/job_technician/jobs/J-NO/technicians/T-NO", None, 404, 404, 403, 403),
    fila("TAREAS", "GET", "/tasks/?limit=100", None, dict(status=200, n="tasks"), dict(status=200, n="tasks"),
         dict(status=200, n="tasks_sub"), dict(status=200, n="tasks_tec")),
    fila("TAREAS", "POST", "/tasks/", {}, (400, 422), (400, 422), (400, 422), 403),
    fila("TAREAS", "PATCH", "/tasks/ZZNOEXISTE", {"Task_status": "Not started"}, 404, 404, 404, 404),
    fila("TAREAS", "PATCH", lambda: f"/tasks/{ids['task_propia']}", {"Task_status": "Not started"}, None, None, None,
         None if PROD else 200),
    fila("TAREAS", "PATCH", lambda: f"/tasks/{ids['task_propia']}", {"Name": "RBAC tech-dev"}, None, None, None,
         None if PROD else dict(status=200, nota="⚠ allowlist Status = Fase B")),
    fila("TAREAS", "DELETE", "/tasks/ZZNOEXISTE", None, del_fa, R3 if PROD else 404, 403, 403),
    fila("FINANZAS", "GET", "/fdocument/?limit=5", None, 200, 200, 403, 403),
    fila("FINANZAS", "GET", "/estimate/?limit=5", None, 200, 200, 403, 403),
    fila("FINANZAS", "GET", "/metrics/financial/summary?type=QID&year=2026", None, (200, 400), (200, 400), 403, 403),
    fila("DASHBOARD", "GET", "/job_metrics/summary", None, 200, 200, 403, 403),
    fila("DASHBOARD", "GET", lambda: f"/subcontractor_metrics/{ids['sub']}", None, 200, 200, 403, 403),
    fila("CHAT", "GET", lambda: f"/chat/job/{ja()}", None, 200, 200, 404, 403),
    fila("CHAT", "GET", lambda: f"/chat/job/{jp()}", None, 200, 200, own_or_skip, None if PROD else 403),
    fila("IAM UI", "GET", "/auth/can?actions=job:delete,member:read,member:read_basics,role:read,commission:read,"
         "commission:read_own,catalog:create,multiplier:create,technician:create,dashboard:read,job:update", None,
         dict(status=200, can={"job:delete": True, "member:read": True, "multiplier:create": True, "commission:read": True}),
         dict(status=200, can={"job:delete": False, "member:read": False, "member:read_basics": True, "role:read": True,
                               "commission:read": False, "commission:read_own": False, "catalog:create": True,
                               "multiplier:create": False, "technician:create": True, "dashboard:read": True, "job:update": True}),
         dict(status=200, can={"job:delete": False, "member:read": False, "dashboard:read": False, "technician:create": False}),
         dict(status=200, can={"job:delete": False, "member:read": False, "dashboard:read": False, "technician:create": False})),
]


def comprobar(esp, st, body):
    """→ (ok, detalle)"""
    if esp is None:
        return None, "—"
    if esp is R3:
        return None, "no ejecutado (R3)"
    if esp is OK:
        return st not in (401, 403), f"{st}"
    if isinstance(esp, int):
        return st == esp, f"{st}"
    if isinstance(esp, tuple):
        return st in esp, f"{st}"
    ok = st == esp["status"]
    det = [str(st)]
    if ok and "n" in esp:
        got = n_of(body)
        key = esp["n"]
        want = tot.get(key) if key in tot else (len(own[key]) if key in ("jobs_sub", "jobs_tec") else own[key])
        if PROD and key in ("jobs_sub", "jobs_tec", "tasks_sub", "tasks_tec"):
            want = 0
        ok = got == want
        det.append(f"n={got}/{want}")
    if ok and "subset" in esp:
        got_ids = {it.get("ID_Jobs") for it in items_of(body)}
        allowed = set() if PROD else own[esp["subset"]]
        ok = got_ids <= allowed
        det.append(f"ids⊆propios ({len(got_ids)})")
    if ok and "sin" in esp:
        its = items_of(body)
        ok = all(esp["sin"] not in it for it in its)
        det.append(f"sin {esp['sin']}" if ok else f"FILTRA {esp['sin']}")
    if ok and "can" in esp:
        res = (body or {}).get("results", {})
        malos = {k: res.get(k) for k, v in esp["can"].items() if res.get(k) is not v}
        ok = not malos
        det.append("can ok" if ok else f"can mal {malos}")
    if "nota" in esp:
        det.append(esp["nota"])
    return ok, " ".join(det)


lineas, fallos = [], 0
print(f"API {API} · entorno {ENT} · ids: " + ", ".join(f"{k}={v}" for k, v in ids.items() if v))
for grupo, metodo, ruta, cuerpo, esperado in FILAS:
    path = ruta() if callable(ruta) else ruta
    celdas = []
    for r in ROLES:
        esp = esperado[r]
        if esp is None or esp is R3:
            ok, det = comprobar(esp, None, None)
        else:
            st, body = call(metodo, path, tokens[r]["token"], cuerpo)
            ok, det = comprobar(esp, st, body)
        mark = "—" if ok is None else ("✅" if ok else "❌")
        if ok is False:
            fallos += 1
        celdas.append(f"{mark} {det}")
    lineas.append(f"| {grupo} | `{metodo} {path}` | " + " | ".join(celdas) + " |")
    print(lineas[-1])

header = ("| grupo | petición | FA | GM | SUB | TEC |\n|---|---|---|---|---|---|\n")
md = f"# Matriz §4.3 · {ENT} · {API}\n\nids: " + ", ".join(f"`{k}={v}`" for k, v in ids.items() if v) + \
     f"\n\ntotales: {tot} · propios: jobs_sub={len(own['jobs_sub'])} jobs_tec={len(own['jobs_tec'])} " \
     f"tasks_sub={own['tasks_sub']} tasks_tec={own['tasks_tec']}\n\n" + header + "\n".join(lineas) + \
     f"\n\n**❌ = {fallos}**\n"
if arg("--md"):
    pathlib.Path(arg("--md")).write_text(md)
    print(f"MD → {arg('--md')}")
print(f"❌ = {fallos}")
sys.exit(1 if fallos else 0)
