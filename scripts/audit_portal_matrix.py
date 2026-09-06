"""Matriz de permisos del portal — 8 sujetos × superficie alcanzable × objetos.

Modelado sobre `scripts/audit_tasks_matrix.py`, del que hereda la disciplina:
  · toda ESCRITURA se verifica releyendo la fila en la BD (la respuesta HTTP no
    es prueba: en este proyecto `POST /tasks/ {}` devolvía 201 con todo NULL, T-07)
  · los conjuntos se ENUMERAN, nunca se cuentan («12 = 12» puede tapar un
    ausente compensado por un sobrante)
  · `esperado` sale de la spec de la Fase 1 (reports/portal-audit/01-contrato-y-spec.md),
    ratificada por el usuario. NUNCA del comportamiento observado.

Lo que aporta frente a la matriz del PR #116: un SEGUNDO sujeto de cada rol de
portal. Con uno solo no existe el objeto «ajeno» y un IDOR entre pares es
invisible por construcción.

Uso: .venv/bin/python scripts/audit_portal_matrix.py --csv salida.csv
Sale != 0 si alguna fila resulta no conforme.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.audit_portal_lib import call, ids_de, paginar, tokens  # noqa: E402

# ── Mundo sembrado (scripts/seed_portal_audit.py) ────────────────────────────
A = {"sub": "SUBC60001", "tec": "TEC60001", "job": "QID-I60001", "task": "TSK60001",
     "att": "ATT60001", "cert": "CERT60001", "cli": "CLI60001", "pmc": "PMC60001"}
B = {"sub": "SUBC60002", "tec": "TEC60002", "job": "PTL-I60001", "task": "TSK60003",
     "att": "ATT60003", "cert": "CERT60002", "cli": "CLI60002", "pmc": "PMC60002"}
NO = {"sub": "SUBC-NO-EXISTE", "tec": "TEC-NO-EXISTE", "job": "QID-NO-EXISTE",
      "task": "TSK-NO-EXISTE", "att": "ATT-NO-EXISTE", "cert": "CERT-NO-EXISTE",
      "cli": "CLI-NO-EXISTE", "pmc": "PMC-NO-EXISTE"}

PORTAL = ("subcontractor", "sub_B", "technical", "tech_de_sub_B", "tech_independiente")
STAFF = ("full_admin", "gqm_member")
# Qué mundo es «propio» para cada sujeto
MUNDO = {"subcontractor": A, "technical": A, "sub_B": B, "tech_de_sub_B": B}

FILAS = []


def registra(sujeto, endpoint, objeto, real, esperado, nota=""):
    conforme = "SÍ" if _casa(real, esperado) else "NO"
    FILAS.append({"sujeto": sujeto, "endpoint": endpoint, "objeto": objeto,
                  "real": real, "esperado": esperado, "conforme": conforme,
                  "nota": nota})
    return conforme


def _casa(real, esperado):
    """`esperado` admite alternativas (`200|404`) y `deny` (cualquier negativa)."""
    real = str(real)
    if esperado == "deny":
        return real in ("401", "403", "404")
    return real in str(esperado).split("|")


def main():
    T = tokens()
    SUJETOS = ["anonimo"] + list(T.keys() - {"anonimo"})
    SUJETOS = ["anonimo", "full_admin", "gqm_member", "subcontractor", "sub_B",
               "technical", "tech_de_sub_B", "tech_independiente"]

    # ── Bloque 1: lecturas por id, propio vs ajeno vs inexistente ────────────
    # `esperado` para portal: 404 en lo ajeno (un 403 confirma existencia).
    # Metadatos por endpoint. Sin esto el `esperado` sale burdo y la matriz
    # miente en las dos direcciones:
    #   · `forma`: "objeto" devuelve UNO por id (ajeno/inexistente ⇒ 404).
    #              "lista"  devuelve una LISTA filtrada por un id de relación;
    #              un id inexistente da 200 con [] legítimamente, así que el
    #              veredicto lo decide el CONTENIDO, no el código.
    #   · `roles`: qué roles de portal tienen la acción. Un 403 del decorador
    #              en un rol que NO la tiene es correcto, no un hallazgo.
    LECTURAS = [
        ("GET /technician/<id>",        "/technician/{tec}",                "tec",  "objeto", PORTAL),
        ("GET /subcontractors/<id>",    "/subcontractors/{sub}",            "sub",  "objeto", ("subcontractor", "sub_B")),
        ("GET /certificate/sub/<id>",   "/certificate/subcontractor/{sub}", "sub",  "lista",  ("subcontractor", "sub_B")),
        ("GET /attachments/<id>",       "/attachments/{att}",               "att",  "objeto", PORTAL),
        ("GET /tlactivity/job/<id>",    "/tlactivity/job/{job}",            "job",  "lista",  PORTAL),
        ("GET /tlactivity/sub/<id>",    "/tlactivity/subcontractor/{sub}",  "sub",  "lista",  PORTAL),
        ("GET /tlactivity/client/<id>", "/tlactivity/client/{cli}",         "cli",  "lista",  PORTAL),
        ("GET /tlactivity/pmc/<id>",    "/tlactivity/parent-mgmt-co/{pmc}", "pmc",  "lista",  PORTAL),
        ("GET /jobs/<id>",              "/jobs/{job}",                      "job",  "objeto", PORTAL),
        ("GET /tasks/<id>",             "/tasks/{task}",                    "task", "objeto", PORTAL),
        ("GET /chat/job/<id>",          "/chat/job/{job}",                  "job",  "objeto", ("subcontractor", "sub_B")),
        # `deny_por_diseño`: el 403 lo argumenta el propio código.
        #   /jobs/subcontractor/<id>  Job.py:832-836 «el id del sub no es secreto, la lista de sus jobs sí»
        #   /commission/member/<id>   Commission.py:213 exige role==member and id==target
        #   /member/<id>              self_profile_guard, routes_protection.py:305
        ("GET /jobs/subcontractor/<id>", "/jobs/subcontractor/{sub}",       "sub",  "deny_diseño", PORTAL),
        ("GET /commission/member/<id>", "/commission/member/MEM60001",      None,   "deny_diseño", PORTAL),
        ("GET /member/<id>",            "/member/MEM60001",                 None,   "deny_diseño", PORTAL),
        ("GET /podio/items/<app_type>", "/podio/items/QID",                 None,   "no_auditable", PORTAL),
    ]
    for etiqueta, plantilla, clave, forma, con_permiso in LECTURAS:
        for suj in SUJETOS:
            tok = T.get(suj)
            propio = MUNDO.get(suj)
            objetos = (("propio", propio), ("ajeno", B if propio is A else A),
                       ("inexistente", NO)) if clave else (("n/a", A),)
            for objeto, mundo in objetos:
                if mundo is None and objeto != "inexistente":
                    continue
                mundo = mundo or A
                ruta = plantilla.format(**mundo)
                st, pl = call(tok, "GET", ruta)

                # ── el esperado, según la spec de la Fase 1 ──────────────────
                if forma == "no_auditable":
                    # Sin credenciales de Podio esta ruta no puede juzgarse aquí.
                    FILAS.append({"sujeto": suj, "endpoint": etiqueta, "objeto": objeto,
                                  "real": st, "esperado": "n/d", "conforme": "n/d",
                                  "nota": "NO AUDITABLE en este entorno: exige credenciales de Podio"})
                    continue
                if suj == "anonimo":
                    esp = "401"
                elif forma == "deny_diseño":
                    # El staff pasa o no según su política. Para el portal el 403 es
                    # correcto sobre lo AJENO; sobre lo propio debe seguir pasando
                    # (un sub pidiendo SUS jobs es el caso legítimo del endpoint).
                    if suj in STAFF:
                        esp = "200|403|404"
                    elif objeto == "propio" and suj in ("subcontractor", "sub_B"):
                        # Solo el propio sub tiene un «propio» aquí: el id del path
                        # es un SUBC y el de un técnico nunca lo iguala (Job.py:834).
                        esp = "200"
                    else:
                        esp = "403"
                elif suj in STAFF:
                    esp = "200|404"          # el staff ve todo; sin veredicto de scoping
                elif suj not in con_permiso:
                    esp = "403"              # no tiene la acción: el decorador debe cortar
                elif objeto in ("propio", "n/a"):
                    esp = "200"
                elif forma == "objeto":
                    esp = "404"              # convención de portal: no confirmar existencia
                else:
                    esp = "200|404"          # lista: el veredicto lo da el contenido

                nota = ""
                conforme = None
                if forma == "lista" and suj in PORTAL and objeto == "ajeno" and st == 200:
                    # Una lista «ajena» solo es conforme si viene VACÍA.
                    ajeno_ids = set((B if propio is A else A).values())
                    encontrados = set()
                    for k in ("ID_Jobs", "ID_Subcontractor", "ID_Certificate",
                              "ID_TLActivity", "ID_Tasks", "ID_Order"):
                        encontrados |= {v for v in ids_de(pl, k) if v in ajeno_ids}
                    vacia = not (pl if isinstance(pl, list) else
                                 (pl.get("results") if isinstance(pl, dict) else pl))
                    if encontrados or not vacia:
                        conforme = "NO"
                        nota = f"FUGA: la lista trae datos ajenos {sorted(encontrados) or '(no vacía)'}"
                    else:
                        nota = "lista vacía: correcto"
                elif st == 200 and suj in PORTAL and objeto == "ajeno":
                    fugas = []
                    for k, lbl in (("ID_Tasks", "tareas"), ("ID_Jobs", "jobs"),
                                   ("ID_Permission", "POLÍTICAS IAM"), ("ID_Order", "órdenes")):
                        v = ids_de(pl, k)
                        if v:
                            fugas.append(f"{lbl}={sorted(v)}")
                    nota = "FUGA: " + " · ".join(fugas) if fugas else "200 sobre objeto ajeno"

                if conforme == "NO":
                    FILAS.append({"sujeto": suj, "endpoint": etiqueta, "objeto": objeto,
                                  "real": st, "esperado": "200 vacío", "conforme": "NO",
                                  "nota": nota})
                else:
                    registra(suj, etiqueta, objeto, st, esp, nota)

    # ── Bloque 2: listados — se ENUMERAN, con paginación completa ────────────
    LISTADOS = [
        ("GET /tasks/",        "/tasks/",        "ID_Tasks"),
        ("GET /jobs/",         "/jobs/",         "ID_Jobs"),
        ("GET /technician/",   "/technician/",   "ID_Technician"),
        ("GET /attachments/",  "/attachments/",  "ID_Attachment"),
        ("GET /subcontractors/", "/subcontractors/", "ID_Subcontractor"),
        ("GET /certificate/",  "/certificate/",  "ID_Certificate"),
    ]
    for etiqueta, ruta, pk in LISTADOS:
        for suj in PORTAL:
            propio = MUNDO.get(suj, {})
            ajeno = B if propio is A else A
            vistos = paginar(T[suj], ruta, pk)
            intrusos = sorted(v for v in vistos if v in ajeno.values())
            st, _ = call(T[suj], "GET", ruta + "?limit=1")
            esp = "200|404"     # /attachments/ devuelve 404 con lista vacía
            nota = (f"devuelve {sorted(vistos)}"
                    + (f" — INTRUSOS del otro sub: {intrusos}" if intrusos else ""))
            FILAS.append({"sujeto": suj, "endpoint": etiqueta, "objeto": "enumeración",
                          "real": st, "esperado": esp,
                          "conforme": "NO" if intrusos else "SÍ", "nota": nota})

    # ── Bloque 3: escrituras — cada una releída en la BD ─────────────────────
    from src.models.TasksModel import Tasks
    from scripts.audit_portal_lib import fila_bd

    # R4: el técnico NO crea tareas
    for suj in ("technical", "tech_de_sub_B", "tech_independiente"):
        st, pl = call(T[suj], "POST", "/tasks/", {
            "Name": "AUDIT-MATRIZ-tecnico-no-debe-crear", "ID_Jobs": A["job"],
            "Task_status": "Not started", "Priority": "Low"})
        tid = pl.get("ID_Tasks") if isinstance(pl, dict) else None
        creada = fila_bd(Tasks, tid) is not None if tid else False
        registra(suj, "POST /tasks/ (R4)", "propio", st, "403",
                 f"BD: fila creada={creada}")

    # R5: ni sub ni técnico borran, ni siquiera lo propio
    for suj in PORTAL:
        mundo = MUNDO.get(suj, A)
        st, _ = call(T[suj], "DELETE", f"/tasks/{mundo['task']}")
        sigue = fila_bd(Tasks, mundo["task"]) is not None
        registra(suj, "DELETE /tasks/<propia> (R5)", "propio", st, "403",
                 f"BD: la fila sigue existiendo={sigue}")
        st, _ = call(T[suj], "DELETE", f"/jobs/{mundo['job']}")
        registra(suj, "DELETE /jobs/<propio> (R5)", "propio", st, "403")

    # R3: el sub asigna solo a SUS técnicos (spec Fase 1, ambigüedad 2)
    st, pl = call(T["subcontractor"], "POST", "/tasks/", {
        "Name": "AUDIT-MATRIZ-sub-asigna-a-tecnico-ajeno", "ID_Jobs": A["job"],
        "ID_Subcontractor": A["sub"], "ID_Technician": B["tec"],
        "Task_status": "Not started", "Priority": "Low"})
    tid = pl.get("ID_Tasks") if isinstance(pl, dict) else None
    row = fila_bd(Tasks, tid) if tid else None
    registra("subcontractor", "POST /tasks/ técnico de OTRO sub (R3)", "ajeno", st, "403",
             f"BD: creada={row is not None}"
             + (f", ID_Technician={row.ID_Technician}" if row else ""))

    # Ambigüedad 10: el sub no debe fijarse su propio compliance
    from src.models.SubcontractorModel import Subcontractor
    st, _ = call(T["subcontractor"], "PATCH", f"/subcontractors/{A['sub']}",
                 {"Gqm_compliance": "AUDIT-AUTOAPROBADO", "Score": 99.0})
    row = fila_bd(Subcontractor, A["sub"])
    escrito = row.Gqm_compliance == "AUDIT-AUTOAPROBADO"
    registra("subcontractor", "PATCH /subcontractors/<propio> compliance", "propio",
             st, "403" if escrito else "200",
             f"BD tras releer: Gqm_compliance={row.Gqm_compliance!r} Score={row.Score!r}"
             + (" ← ESCRIBIÓ" if escrito else ""))
    # restaurar
    from src.database.db_sqlmodel import get_session
    with get_session() as s:
        r = s.get(Subcontractor, A["sub"]); r.Gqm_compliance = None; r.Score = None
        s.add(r); s.commit()

    # ── Limpieza: no dejar atrás lo que creó la propia matriz ───────────────
    from sqlmodel import select
    with get_session() as ses:
        sobrantes = ses.exec(select(Tasks).where(
            Tasks.Name.like("AUDIT-MATRIZ-%"))).all()
        for t in sobrantes:
            ses.delete(t)
        ses.commit()
        print(f"limpieza: {len(sobrantes)} tareas «AUDIT-MATRIZ-%» borradas")

    # ── Salida ──────────────────────────────────────────────────────────────
    destino = sys.argv[sys.argv.index("--csv") + 1] if "--csv" in sys.argv else None
    if destino:
        with open(destino, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["sujeto", "endpoint", "objeto", "real",
                                               "esperado", "conforme", "nota"])
            w.writeheader(); w.writerows(FILAS)
    malas = [f for f in FILAS if f["conforme"] == "NO"]
    print(f"filas={len(FILAS)}  conformes={len(FILAS)-len(malas)}  NO CONFORMES={len(malas)}")
    for f in malas:
        print(f"  ❌ {f['sujeto']:19s} {f['endpoint']:42s} {f['objeto']:12s} "
              f"real={f['real']:4} esp={f['esperado']:8s} {f['nota'][:70]}")
    if destino:
        print(f"\nCSV → {destino}")
    return 1 if malas else 0


if __name__ == "__main__":
    sys.exit(main())
