"""Utilidades compartidas de la auditoría de portal.

Sin dependencias fuera de la stdlib, igual que `audit_tasks_matrix.py`: el repo
no trae httpx ni requests para los arneses, y añadirlo por comodidad sería
cambiar el entorno que se está auditando.
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decouple import config  # noqa: E402

from src.utils.db_guard import require_dev_database  # noqa: E402

require_dev_database(config, contexto="auditoría de portal")

API = os.environ.get("E2E_API", "http://127.0.0.1:8000").rstrip("/")
PW = config("SEED_DEV_PASSWORD")

# slug -> (correo, tipo). `anonimo` no tiene credenciales: es la ausencia de token.
SUJETOS = {
    "full_admin":         ("admin-dev@senavia-test.com", "member"),
    "gqm_member":         ("member-dev@senavia-test.com", "member"),
    "subcontractor":      ("sub-dev@senavia-test.com", "subcontractor"),
    "sub_B":              ("sub-b-dev@senavia-test.com", "subcontractor"),
    "technical":          ("tech-dev@senavia-test.com", "technician"),
    "tech_de_sub_B":      ("tech-b-dev@senavia-test.com", "technician"),
    "tech_independiente": ("tech-indep-dev@senavia-test.com", "technician"),
}


def login(email: str) -> str:
    req = urllib.request.Request(
        f"{API}/auth/login",
        data=json.dumps({"Email_Address": email, "Password": PW}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["access_token"]


def tokens() -> dict:
    """Un token por sujeto. `anonimo` -> None (sin cabecera Authorization)."""
    t = {"anonimo": None}
    for slug, (email, _) in SUJETOS.items():
        t[slug] = login(email)
    return t


def call(token, method: str, path: str, body=None):
    """Devuelve (status, payload). Nunca lanza: un error HTTP es un dato."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{API}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw)
            except Exception:
                return r.status, raw.decode(errors="replace")[:400]
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw.decode(errors="replace")[:400]
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


def ids_de(payload, clave: str) -> set:
    """Enumera identificadores. NUNCA se cuenta: «12 = 12» puede tapar un
    ausente compensado por un sobrante."""
    out = set()

    def anda(n):
        if isinstance(n, dict):
            if clave in n and isinstance(n[clave], str):
                out.add(n[clave])
            for v in n.values():
                anda(v)
        elif isinstance(n, list):
            for v in n:
                anda(v)

    anda(payload)
    return out


def paginar(token, path: str, clave: str, limite: int = 100) -> set:
    """Recorre TODAS las páginas.

    `@paginate()` (src/utils/pagination.py) topa `limit` en 100 y rebana en
    Python; `total` es el recuento sin paginar. Quedarse en la página 1 haría
    pasar por «scoping» lo que solo es un corte de página.
    """
    vistos, page = set(), 1
    while True:
        sep = "&" if "?" in path else "?"
        st, pl = call(token, "GET", f"{path}{sep}page={page}&limit={limite}")
        if st != 200:
            return vistos
        vistos |= ids_de(pl, clave)
        total = pl.get("total") if isinstance(pl, dict) else None
        results = pl.get("results") if isinstance(pl, dict) else pl
        if not isinstance(results, list) or not results:
            return vistos
        if total is None or page * limite >= total:
            return vistos
        page += 1


def fila_bd(modelo, pk):
    """Relee la fila. La respuesta HTTP no es prueba de escritura: en este
    proyecto un `POST /tasks/ {}` devolvía 201 con todo NULL (T-07)."""
    from src.database.db_sqlmodel import get_session
    with get_session() as s:
        return s.get(modelo, pk)
