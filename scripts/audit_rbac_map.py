"""Mapa mecánico de autorización: qué protege cada ruta registrada en `app.url_map`.

No consulta la BD (el engine es perezoso; con el .env de dev basta). Para cada
regla × método resuelve el mecanismo leyendo las closures reales de los
decoradores (`require_permission` → free-var `actions`; `require_role` →
`allowed_roles`) y el `before_request` que instala `protect_blueprint`
(`_authorize` → `resource`/`fixed_action`/`overrides`). Nada de grep: si el
código cambia, el mapa cambia.

Uso:  .venv/bin/python scripts/audit_rbac_map.py [--csv ruta.csv]
"""
import csv, os, sys, pathlib
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/fake")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("APP_ENV", "test")

from main import app  # noqa: E402

# Copia literal de main.py (public_prefixes) + "/" — si main.py cambia, cambiar aquí.
PUBLIC_PREFIXES = [
    "/auth/login", "/auth/refresh", "/auth/forgot-password", "/auth/reset-password",
    "/webhook/podio/jobs", "/webhook/podio/others", "/webhook/qbo", "/callback",
    "/admin/podio/reconciliar_cron", "/qbo/refresh_tokens_cron",
]

VERB_ACTION = {"GET": "read", "HEAD": "read", "DELETE": "delete", "POST": "create"}


def closure_vars(fn):
    code = getattr(fn, "__code__", None)
    cells = getattr(fn, "__closure__", None) or ()
    if not code or not cells:
        return {}
    return dict(zip(code.co_freevars, [c.cell_contents for c in cells]))


def view_mechanisms(view):
    """Recorre la cadena de wrappers y devuelve [(mecanismo, acciones)]."""
    found = []
    fn, seen = view, 0
    while fn is not None and seen < 20:
        cv = closure_vars(fn)
        if "actions" in cv and "resource" in cv:
            acts = cv["actions"]
            acts = [acts] if isinstance(acts, str) else list(acts)
            res = cv.get("resource", "*")
            found.append(("require_permission", "|".join(acts) + ("" if res == "*" else f"@{res}")))
        elif "allowed_roles" in cv:
            found.append(("require_role", "|".join(cv["allowed_roles"])))
        fn = getattr(fn, "__wrapped__", None)
        seen += 1
    return found


def blueprint_mechanism(bp_name, func_name, method):
    for f in app.before_request_funcs.get(bp_name, []):
        if getattr(f, "__name__", "") != "_authorize":
            continue
        cv = closure_vars(f)
        overrides = cv.get("overrides") or {}
        if func_name in overrides:
            act = overrides[func_name]
            return ("protect_blueprint", act if act else "exento")
        if cv.get("fixed_action"):
            return ("protect_blueprint", cv["fixed_action"])
        return ("protect_blueprint", f"{cv['resource']}:{VERB_ACTION.get(method, 'update')}")
    return None


rows = []
for rule in app.url_map.iter_rules():
    view = app.view_functions[rule.endpoint]
    bp_name, _, func_name = rule.endpoint.rpartition(".")
    for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
        mechs = view_mechanisms(view)
        bpm = blueprint_mechanism(bp_name, func_name, method) if bp_name else None
        if bpm:
            mechs.append(bpm)
        if not mechs:
            public = rule.rule == "/" or any(rule.rule.startswith(p) for p in PUBLIC_PREFIXES)
            mechs = [("public", "") if public else ("jwt-only", "")]
        rows.append({
            "method": method, "rule": rule.rule, "endpoint": rule.endpoint,
            "actions": " + ".join(a for _, a in mechs if a),
            "mechanism": " + ".join(m for m, _ in mechs),
        })

rows.sort(key=lambda r: (r["rule"], r["method"]))
if "--csv" in sys.argv:
    path = sys.argv[sys.argv.index("--csv") + 1]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["method", "rule", "endpoint", "actions", "mechanism"])
        w.writeheader(); w.writerows(rows)
    print(f"CSV → {path} ({len(rows)} filas)")

print(Counter(r["mechanism"] for r in rows).most_common())
jwt_only = [f'{r["method"]} {r["rule"]}' for r in rows if r["mechanism"] == "jwt-only"]
print(f"jwt-only ({len(jwt_only)}):", *jwt_only, sep="\n  ")
