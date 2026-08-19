#!/usr/bin/env python3
"""Cambios de IAM en produccion para la entrega de gqmconnect.com.

Todo pasa por los endpoints de la API (nunca SQL directo), asi que respeta las
validaciones, los 409 de integridad y los IDs generados por el servidor.

  DRY RUN por defecto:  python3 scripts/entrega_iam_produccion.py
  Aplicar de verdad:    python3 scripts/entrega_iam_produccion.py --aplicar

Pide el correo y la contrasena de un Full Admin por stdin. La contrasena no se
imprime, no se guarda y no se pasa por argumentos (que quedarian en el historial
del shell). Requiere que gqm-api este desplegada con /auth/me si quieres el
bloque de verificacion final; el resto funciona sin el.
"""
import argparse
import getpass
import json
import os
import secrets
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("GQM_API_URL", "https://gqm-api.vercel.app").rstrip("/")

# ── Que se toca y por que ────────────────────────────────────────────────────
TECNICO_JJ = "TEC60001"          # «Juan Jose Jimenez Tech», juanjj272001@gmail.com
PERM_TECNICO_JJ = "PERM60005"    # «Basic Technician View»: job:update, subcontractor:update...

# Deny que se anade a la politica de GQM Member (PERM60008). Se usa el comodin
# porque la decision fue ocultar Comisiones a los GQM Member. Ojo: `commission:*`
# tambien alcanza `commission:read_own`. Si en algun momento se quiere que un
# miembro vea SUS comisiones, cambiar por ["commission:read", "commission:update"],
# que es exactamente lo que denegaba el rol viejo «GQM Inc - Acc Rep».
DENY_COMISIONES = ["commission:*"]

ROLES_A_DESACTIVAR = [
    ("ROL60001", "Standard Admin Role — superusuario dormido con Allow *:* y 0 miembros"),
    ("ROL60002", "GQM Inc - Acc Rep — legado del modelo anterior, 0 miembros"),
]
PERMISOS_A_DESACTIVAR = [
    ("PERM60002", "Add New GQM Members — Document NULL y sin rol: huerfano"),
    ("PERM60003", "Add New Subs — Document NULL, colgaba de ROL60002"),
    ("PERM60006", "GQM analyst — huerfano, sin rol"),
]
DESENLACES = [("PERM60003", "ROL60002")]

APLICAR = False
TOKEN = None


def _peticion(metodo, ruta, cuerpo=None, token=None):
    url = f"{BASE}{ruta}"
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, method=metodo)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        cuerpo_err = e.read().decode()
        try:
            return e.code, json.loads(cuerpo_err or "{}")
        except json.JSONDecodeError:
            return e.code, {"raw": cuerpo_err[:300]}
    except Exception as e:
        return 0, {"error": str(e)}


def paso(descripcion, metodo, ruta, cuerpo=None):
    """Ejecuta un cambio, o lo describe si estamos en dry run."""
    if not APLICAR:
        extra = f"  body={json.dumps(cuerpo)}" if cuerpo else ""
        print(f"   [DRY] {metodo} {ruta}{extra}")
        print(f"         → {descripcion}")
        return True
    codigo, respuesta = _peticion(metodo, ruta, cuerpo, TOKEN)
    ok = 200 <= codigo < 300
    marca = "✅" if ok else ("➖" if codigo == 404 else "❌")
    print(f"   {marca} {codigo} {metodo} {ruta}")
    if not ok and codigo != 404:
        print(f"      {json.dumps(respuesta)[:220]}")
    print(f"      → {descripcion}")
    return ok or codigo == 404


def main():
    global APLICAR, TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true",
                    help="escribe de verdad en produccion (por defecto: dry run)")
    args = ap.parse_args()
    APLICAR = args.aplicar

    print(f"\nAPI: {BASE}")
    print("MODO: " + ("🔴 APLICAR (escribe en produccion)" if APLICAR else "🔵 DRY RUN (no escribe nada)"))

    if APLICAR:
        print("\nCredenciales de un Full Admin (no se guardan ni se imprimen):")
        correo = input("  correo: ").strip()
        clave = getpass.getpass("  contrasena: ")
        codigo, datos = _peticion("POST", "/auth/login",
                                  {"Email_Address": correo, "Password": clave})
        clave = None
        if codigo != 200 or "access_token" not in datos:
            sys.exit(f"⛔ login fallido ({codigo}): {json.dumps(datos)[:200]}")
        TOKEN = datos["access_token"]
        rol = (datos.get("user_data") or {}).get("role_detail") or {}
        print(f"  ✅ dentro como {(datos.get('user_data') or {}).get('Member_Name')} — rol {rol.get('Name')}")
        if rol.get("Name") != "Full Admin":
            sys.exit("⛔ ese usuario no es Full Admin: los endpoints IAM exigen iam:manage")

    print("\n" + "=" * 74)
    print("PASO 0 — cerrar el acceso del tecnico de Juan Jose")
    print("=" * 74)
    paso(f"revocar {PERM_TECNICO_JJ} a {TECNICO_JJ}: se queda sin ninguna politica → 403 en todo",
         "DELETE", f"/permission_tech/permission/{PERM_TECNICO_JJ}/tech/{TECNICO_JJ}")
    nueva = secrets.token_urlsafe(48)
    paso(f"invalidar la contrasena de {TECNICO_JJ} (la fila NO se borra: hay tlactivity apuntando)",
         "PATCH", f"/technician/{TECNICO_JJ}", {"Password": nueva})
    print("   ℹ️  La revocacion del permiso es el control real. Aunque recuperase la")
    print("      contrasena por /auth/forgot-password, entraria sin politicas: 403 en todo.")

    print("\n" + "=" * 74)
    print("PASO 5.1 — ocultar Comisiones a los GQM Member (PERM60008)")
    print("=" * 74)
    codigo, actual = (200, None) if not APLICAR else _peticion("GET", "/permission/PERM60008", token=TOKEN)
    if APLICAR:
        if codigo != 200:
            sys.exit(f"⛔ no se pudo leer PERM60008 ({codigo})")
        doc = actual.get("Document") or {}
    else:
        # Documento conocido en produccion a 19-ago-2026, solo para previsualizar.
        doc = {"Statement": [
            {"Action": ["*"], "Effect": "Allow", "Resource": ["*"]},
            {"Action": ["iam:*", "qbo:*", "admin:*", "role:create", "role:update",
                        "role:delete", "permission:create", "permission:update",
                        "permission:delete", "member:create", "member:update",
                        "member:delete", "job:force_delete"],
             "Effect": "Deny", "Resource": ["*"]}]}

    denies = [s for s in doc.get("Statement", []) if s.get("Effect") == "Deny"]
    if not denies:
        sys.exit("⛔ PERM60008 no tiene ningun statement Deny: revisar a mano antes de tocar nada")
    faltan = [a for a in DENY_COMISIONES if a not in denies[0].get("Action", [])]
    if not faltan:
        print("   ➖ el Deny de comisiones ya estaba puesto, no se toca")
    else:
        denies[0]["Action"] = denies[0].get("Action", []) + faltan
        paso(f"anadir {faltan} al Deny — corta tambien la API y la URL directa, no solo el menu",
             "PATCH", "/permission/PERM60008", {"Document": doc})

    print("\n" + "=" * 74)
    print("PASO 3 — limpiar roles y permisos huerfanos")
    print("=" * 74)
    for perm, rol_id in DESENLACES:
        paso(f"desenlazar {perm} de {rol_id} (si no, el DELETE/PATCH posterior choca con un 409)",
             "DELETE", f"/permission_role/permission/{perm}/role/{rol_id}")
    for rol_id, motivo in ROLES_A_DESACTIVAR:
        paso(motivo, "PATCH", f"/role/{rol_id}", {"Active": False})
    for perm, motivo in PERMISOS_A_DESACTIVAR:
        paso(motivo, "PATCH", f"/permission/{perm}", {"Active": False})
    print("\n   Se desactiva en vez de borrar: se conserva el documento por si hay que")
    print("   auditar que concedia, y un DELETE con enlaces vivos devolveria 409.")
    print("   NO se toca MEM60011 (Juan Jose, miembro): borrarlo destruiria sus 99")
    print("   filas de tlactivity restantes, y ya esta sin rol ni permisos.")

    if not APLICAR:
        print("\n🔵 Dry run: no se ha escrito nada. Repite con --aplicar para ejecutarlo.\n")
        return

    print("\n" + "=" * 74)
    print("VERIFICACION")
    print("=" * 74)
    codigo, res = _peticion("GET", "/auth/can?actions=iam:manage,commission:read,job:update",
                            token=TOKEN)
    print(f"   Full Admin → {json.dumps(res.get('results', res))}")
    codigo, roles = _peticion("GET", "/role/", token=TOKEN)
    if codigo == 200:
        items = roles if isinstance(roles, list) else roles.get("items", roles.get("data", []))
        for r in items or []:
            if isinstance(r, dict) and r.get("ID_Role"):
                print(f"   {r['ID_Role']:<10} {str(r.get('Name'))[:26]:<28} Active={r.get('Active')}")
    print("\n   Falta comprobar a mano, con una sesion de GQM Member:")
    print("     • /auth/can?actions=commission:read,iam:manage → false en las dos")
    print("     • login con juanjj272001@gmail.com → 401")
    print()


if __name__ == "__main__":
    main()
