#!/usr/bin/env python3
"""Aplica en PRODUCCIÓN la spec RBAC de Fase A sobre `permission.Document` (solo 2 filas):
  gqm-member-operativo  → Deny += job:delete, member:read, multiplier:create/update/delete
  subcontractor-portal  → Allow −= finance:read

Por defecto DRY-RUN: respalda 6 tablas a CSV, comprueba que la BD está EXACTAMENTE
en el baseline conocido (si alguien la tocó, aborta) e imprime el diff. Solo con
--aplicar escribe, en UNA transacción, y relee para verificar.

  GQM_PROD_DATABASE_URL=...  (exportada con `read -s`; aquí solo se imprime el host)
  --aplicar              escribe
  --ensayo-develop       exige host develop; salta la aserción de baseline/IDs
                         (ensayo de respaldo → aplicar → restaurar, no de contenido)
  --restaurar DIR        restaura las 2 filas desde DIR/permission.csv (por ID_Permission)
  --dir RUTA             carpeta de respaldos (defecto ~/outputs/gqm-entrega)
Nunca borra nada. Nunca imprime la URL.
"""
import csv, datetime as dt, hashlib, json, os, pathlib, sys
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import Json

argv = sys.argv[1:]
APLICAR = "--aplicar" in argv
ENSAYO = "--ensayo-develop" in argv
RESTAURAR = argv[argv.index("--restaurar") + 1] if "--restaurar" in argv else None
BASE_DIR = pathlib.Path(argv[argv.index("--dir") + 1] if "--dir" in argv else "~/outputs/gqm-entrega").expanduser()

URL = os.environ.get("GQM_PROD_DATABASE_URL")
if not URL:
    sys.exit("⛔ falta GQM_PROD_DATABASE_URL en el entorno (export con `read -s`)")
HOST = urlparse(URL).hostname or "?"
DEV = "ep-sparkling-sound" in HOST
if ENSAYO and not DEV:
    sys.exit(f"⛔ --ensayo-develop exige host develop; host={HOST}")
if not ENSAYO and DEV:
    sys.exit(f"⛔ host develop sin --ensayo-develop; host={HOST}")
print(f"host={HOST} · modo={'ENSAYO develop' if ENSAYO else 'PRODUCCIÓN'} · {'APLICAR' if APLICAR else 'dry-run'}")

TABLAS = ["permission", "role", "permission_role", "permission_member", "permission_tech", "permission_subc"]
GESTIONADAS = ["full-admin-all", "gqm-member-operativo", "subcontractor-portal", "technical-portal"]
IDS_PROD = {"gqm-member-operativo": "PERM60008", "subcontractor-portal": "PERM60009"}

DENY_GM_ANTES = ["iam:*", "qbo:*", "admin:*", "role:create", "role:update", "role:delete",
                 "permission:create", "permission:update", "permission:delete",
                 "member:create", "member:update", "member:delete", "job:force_delete", "commission:*"]
DENY_GM_DESPUES = DENY_GM_ANTES + ["job:delete", "member:read",
                                   "multiplier:create", "multiplier:update", "multiplier:delete"]
ALLOW_SUB_ANTES = ["job:read", "job:read_basics", "finance:read", "tasks:read", "tasks:read_own", "tasks:create",
                   "tasks:update", "subcontractor:read", "technician:read", "skill:read", "attachment:read",
                   "attachment:read_technicians", "attachment:create", "certificate:read", "profile:update_own"]
ALLOW_SUB_DESPUES = [a for a in ALLOW_SUB_ANTES if a != "finance:read"]

BASELINE = {
    "gqm-member-operativo": {"Statement": [
        {"Effect": "Allow", "Action": ["*"], "Resource": ["*"]},
        {"Effect": "Deny", "Action": DENY_GM_ANTES, "Resource": ["*"]}]},
    "subcontractor-portal": {"Statement": [
        {"Effect": "Allow", "Action": ALLOW_SUB_ANTES, "Resource": ["*"]}]},
}
DESPUES = {
    "gqm-member-operativo": {"Statement": [
        {"Effect": "Allow", "Action": ["*"], "Resource": ["*"]},
        {"Effect": "Deny", "Action": DENY_GM_DESPUES, "Resource": ["*"]}]},
    "subcontractor-portal": {"Statement": [
        {"Effect": "Allow", "Action": ALLOW_SUB_DESPUES, "Resource": ["*"]}]},
}


def norm(doc):
    """Forma canónica: lista de (Effect, multiconjunto de Action, multiconjunto de Resource)."""
    return [(s.get("Effect"), tuple(sorted(s.get("Action", []))), tuple(sorted(s.get("Resource", []))))
            for s in (doc or {}).get("Statement", [])]


def diff(nombre, antes, despues):
    print(f"\n— {nombre}")
    for i, (a, d) in enumerate(zip(antes["Statement"], despues["Statement"])):
        quitadas = sorted(set(a["Action"]) - set(d["Action"]))
        nuevas = sorted(set(d["Action"]) - set(a["Action"]))
        if quitadas or nuevas:
            print(f"  Statement[{i}] {a['Effect']}: " + " ".join(f"-{x}" for x in quitadas) + " " + " ".join(f"+{x}" for x in nuevas))
        else:
            print(f"  Statement[{i}] {a['Effect']}: sin cambio ({len(a['Action'])} acciones)")


def respaldar(cur):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = BASE_DIR / f"respaldo-rbac-{stamp}"
    out.mkdir(parents=True, exist_ok=False)
    manifest = []
    for t in TABLAS:
        cur.execute("select column_name from information_schema.columns where table_schema='public' and table_name=%s order by ordinal_position", (t,))
        cols = [r[0] for r in cur.fetchall()]
        if not cols:
            sys.exit(f"⛔ tabla {t} sin columnas (¿esquema?)")
        collist = ", ".join(f'"{c}"' for c in cols)
        path = out / f"{t}.csv"
        with open(path, "w", newline="") as fh:
            cur.copy_expert(f"COPY (SELECT {collist} FROM \"{t}\" ORDER BY 1) TO STDOUT WITH (FORMAT csv, HEADER, NULL '\\N')", fh)
        cur.execute(f'select count(*) from "{t}"')
        n = cur.fetchone()[0]
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest.append(f"{t}\tfilas={n}\tsha256={sha}\tcolumnas={','.join(cols)}")
    cur.execute('select "ID_Permission","Name",md5("Document"::text) from permission where "Name" = any(%s) order by 1', (GESTIONADAS,))
    for pid, name, m in cur.fetchall():
        manifest.append(f"md5_document\t{pid}\t{name}\t{m}")
    (out / "manifest.txt").write_text("\n".join(manifest) + "\n")
    print(f"respaldo → {out} ({len(TABLAS)} tablas)")
    return out


def leer_actuales(cur):
    cur.execute('select "ID_Permission","Name","Active","Document" from permission where "Name" = any(%s) order by "Name"',
                (list(BASELINE),))
    filas = cur.fetchall()
    por_nombre = {}
    for pid, name, active, doc in filas:
        por_nombre.setdefault(name, []).append((pid, active, doc))
    for name in BASELINE:
        if len(por_nombre.get(name, [])) != 1:
            sys.exit(f"⛔ {name}: esperaba exactamente 1 fila, hay {len(por_nombre.get(name, []))}")
        pid, active, doc = por_nombre[name][0]
        if not active:
            sys.exit(f"⛔ {name} ({pid}) no está Active")
    return {name: por_nombre[name][0] for name in BASELINE}


def restaurar(cur, dir_):
    path = pathlib.Path(dir_).expanduser() / "permission.csv"
    with open(path, newline="") as fh:
        filas = list(csv.DictReader(fh))
    objetivo = [f for f in filas if f["Name"] in BASELINE]
    if len(objetivo) != 2:
        sys.exit(f"⛔ {path}: esperaba 2 filas gestionadas, hay {len(objetivo)}")
    for f in objetivo:
        doc = None if f["Document"] == "\\N" else json.loads(f["Document"])
        cur.execute('update permission set "Document"=%s where "ID_Permission"=%s', (Json(doc) if doc is not None else None, f["ID_Permission"]))
        if cur.rowcount != 1:
            raise RuntimeError(f"rowcount={cur.rowcount} al restaurar {f['ID_Permission']}")
        print(f"  restaurado {f['ID_Permission']} {f['Name']} ({len(doc['Statement'])} statements)")


def main():
    conn = psycopg2.connect(URL)
    conn.autocommit = False
    try:
        cur = conn.cursor()
        if RESTAURAR:
            print(f"RESTAURAR desde {RESTAURAR}")
            restaurar(cur, RESTAURAR)
            conn.commit()
            actuales = leer_actuales(cur)
            for name, (pid, _, doc) in actuales.items():
                print(f"  {pid} {name}: {len(doc['Statement'][-1]['Action'])} acciones en el último statement")
            return
        respaldo = respaldar(cur)
        actuales = leer_actuales(cur)
        for name, (pid, _, doc) in actuales.items():
            if not ENSAYO and IDS_PROD[name] != pid:
                sys.exit(f"⛔ {name} es {pid}, esperaba {IDS_PROD[name]} — ¿esta BD es producción?")
            if norm(doc) != norm(BASELINE[name]):
                msg = f"{name} ({pid}) NO está en el baseline conocido"
                if ENSAYO:
                    print(f"⚠ {msg} (ensayo: se continúa)")
                else:
                    print(f"  actual: {json.dumps(doc, sort_keys=True)}")
                    sys.exit(f"⛔ {msg} — alguien tocó la BD; PARAR y reportar")
            diff(f"{pid} {name}", doc if ENSAYO else BASELINE[name], DESPUES[name])
        if not APLICAR:
            conn.rollback()
            print("\ndry-run: nada escrito. Para aplicar: --aplicar")
            return
        print("\nAPLICANDO (una transacción)…")
        for name, (pid, _, doc) in actuales.items():
            cur.execute('update permission set "Document"=%s where "Name"=%s and "Document"=%s::jsonb',
                        (Json(DESPUES[name]), name, json.dumps(doc)))
            if cur.rowcount != 1:
                raise RuntimeError(f"rowcount={cur.rowcount} en {name}; rollback")
        releidas = leer_actuales(cur)
        for name, (pid, _, doc) in releidas.items():
            if norm(doc) != norm(DESPUES[name]):
                raise RuntimeError(f"relectura de {name} no coincide con DESPUES; rollback")
        conn.commit()
        cur.execute("select to_char(now() at time zone 'UTC','YYYY-MM-DD HH24:MI:SS')")
        print(f"✅ aplicado y verificado · {cur.fetchone()[0]} UTC · respaldo en {respaldo}")
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        sys.exit(f"⛔ {e} — rollback hecho, nada escrito")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
