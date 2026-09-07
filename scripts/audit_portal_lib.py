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


# ── Los mundos sembrados, resueltos POR NOMBRE ───────────────────────────────
#
# `audit_portal_matrix.py` y `audit_field_leaks.py` traían los ids escritos a
# mano (ATT60001, TSK60003, QID-I60001…). Esos ids los da un CONTADOR, y ni
# `--limpiar` lo reinicia: en cuanto la base no es virgen, o alguien siembra una
# fila más, apuntan a otra cosa. Medido: al añadir cuatro adjuntos al mundo A,
# ATT60003 pasó de ser «el adjunto de B» a ser uno de A, y la matriz reportó 14
# filas NO CONFORMES que no eran ningún fallo de permisos — comparaba objetos de
# A contra las expectativas de B. Después de un `--limpiar` + resiembra, los ids
# viejos directamente no existen y las sondas se saltan solas.
#
# Una sonda que se salta sola, o que compara el objeto equivocado, es peor que
# no tenerla: da un veredicto con la misma cara que el bueno.
MARCA_SIEMBRA = "AUDIT-PORTAL"


def mundos_sembrados():
    """(A, B): los dos mundos de `seed_portal_audit.py`, leídos de la BD.

    Las variables de entorno siguen mandando si están puestas, para poder
    apuntar la auditoría a un mundo distinto sin tocar el código.
    """
    from sqlmodel import select

    from src.database.db_sqlmodel import get_session
    from src.models.AttachmentsModel import Attachments
    from src.models.CertificateModel import Certificate
    from src.models.ClientModel import Client
    from src.models.JobModel import Job
    from src.models.SubcontractorModel import Subcontractor
    from src.models.TasksModel import Tasks
    from src.models.TechnicianModel import Technician

    def uno(s, modelo, campo, valor, que):
        fila = s.exec(select(modelo).where(getattr(modelo, campo) == valor)).first()
        if fila is None:
            sys.exit(f"⛔ no encuentro {que} («{valor}»). Corre "
                     f"scripts/seed_rbac.py y scripts/seed_portal_audit.py.")
        return fila

    with get_session() as s:
        mundos = {}
        for letra, correo_sub, correo_tec in (
                ("A", "sub-dev@senavia-test.com", "tech-dev@senavia-test.com"),
                ("B", "sub-b-dev@senavia-test.com", "tech-b-dev@senavia-test.com")):
            m = f"{MARCA_SIEMBRA}-{letra}"
            cli = uno(s, Client, "Client_Community", f"{m}-cliente", f"cliente {letra}")
            mundos[letra] = {
                "sub": uno(s, Subcontractor, "Email_Address", correo_sub,
                           f"subcontratista {letra}").ID_Subcontractor,
                "tec": uno(s, Technician, "Email_Address", correo_tec,
                           f"técnico {letra}").ID_Technician,
                "job": uno(s, Job, "Project_name", f"{m}-job-de-sub-{letra}",
                           f"job {letra}").ID_Jobs,
                "task": uno(s, Tasks, "Name", f"{m}-tarea-de-tech-{letra}",
                            f"tarea {letra}").ID_Tasks,
                # El adjunto «propio y legible». Ojo: NO es `-adjunto-job`, que
                # es `access_level="internal"`; de un job, un rol de portal solo
                # ve la carpeta «technicians». Apuntar aqui al `internal` hacia
                # que la matriz esperase 200 sobre algo que ahora es 403 — y esa
                # expectativa es el contrato viejo, no un fallo.
                "att": uno(s, Attachments, "Document_name",
                           f"{m}-adjunto-tecnico" if letra == "A" else f"{m}-adjunto-tecnico",
                           f"adjunto {letra}").ID_Attachment,
                "att_internal": uno(s, Attachments, "Document_name", f"{m}-adjunto-job",
                                    f"adjunto interno {letra}").ID_Attachment,
                # La tarea del job propio SIN tecnico asignado: la usan las
                # sondas de escritura (R5) sobre un objeto propio.
                "task_sin_asignar": uno(
                    s, Tasks, "Name", f"{MARCA_SIEMBRA}-A-tarea-sin-asignar",
                    "tarea sin asignar de A").ID_Tasks if letra == "A" else None,
                "cert": uno(s, Certificate, "Name", f"{m}-certificado",
                            f"certificado {letra}").ID_Certificate,
                "cli": cli.ID_Client,
                "pmc": cli.ID_Community_Tracking,
            }
        for nivel in ("technicians", "members", "logbook", "sin-nivel"):
            mundos["A"][f"att_{nivel}"] = uno(
                s, Attachments, "Document_name",
                f"{MARCA_SIEMBRA}-A-adjunto-job-{nivel}",
                f"adjunto de job A nivel {nivel}").ID_Attachment

        compartido = uno(s, Job, "Project_name",
                         f"{MARCA_SIEMBRA}-D-job-compartido-A-y-B", "job compartido")
        mundos["A"]["compartido"] = mundos["B"]["compartido"] = compartido.ID_Jobs

    for letra in ("A", "B"):
        for clave in list(mundos[letra]):
            var = f"AUDIT_{letra}_{clave.upper()}"
            if os.environ.get(var):
                mundos[letra][clave] = os.environ[var]
    return mundos["A"], mundos["B"]
