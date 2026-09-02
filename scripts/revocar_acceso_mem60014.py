#!/usr/bin/env python3
"""Revoca el acceso de MEM60014 (Jeferson Forero) a produccion.

Contrato v8.0 num. 9.4: prohibicion absoluta y permanente de acceder a
cualquier sistema tras la terminacion. Su aporte de codigo ceso el 29-jul-2026.

  DRY RUN por defecto:  python3 scripts/revocar_acceso_mem60014.py
  Aplicar de verdad:    python3 scripts/revocar_acceso_mem60014.py --aplicar

Todo pasa por los endpoints del API (nunca SQL directo), asi que respeta las
validaciones, el hasheo de contrasena y la auditoria (@audit "Member updated").
Pide correo y contrasena de un Full Admin por stdin; la contrasena no se
imprime, no se guarda y no viaja por argumentos.

POR QUE ESTE DISEÑO (medido sobre el codigo, no supuesto)
---------------------------------------------------------
1. Rol nuevo con Active=false y CERO permisos enlazados, en vez de reutilizar
   uno existente. ROL60001 «Standard Admin Role» parece el destino natural
   (Active=false, 0 miembros) pero lleva PERM60004 con `Allow *:*` ACTIVO:
   mandarlo alli le habria dado permisos comodin. Es una trampa.
2. Cero permisos basta, no hace falta un documento `Deny *:*`:
   PolicyEvaluator.evaluate() arranca en `allowed = False`
   (src/utils/policy_evaluator.py), asi que una lista vacia deniega todo.
3. Muerde en la SIGUIENTE peticion: las politicas se releen por request
   (joinedload de Member.role en routes_protection.py), no vienen en el JWT.
4. Mata la sesion en <=60 min sin desloguear a nadie mas: /refresh devuelve
   401 si `role.Active is False` (REG-100, Login_auth.py). Por eso el rol se
   crea INACTIVO: es lo que cierra la sesion viva.
5. La fila NO se borra: hay 2 purchase y 2 tlactivity apuntando a MEM60014, y
   el rastro de auditoria sostiene los numerales 9.3 y 6.6 del contrato.
6. Member no tiene campo `Active` (comprobado en MemberModel.py): las unicas
   palancas son el rol y la contrasena. Por eso se usan las dos.
"""
import argparse
import getpass
import json
import os
import secrets
import ssl
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("GQM_API_URL", "https://gqm-api.vercel.app").rstrip("/")

OBJETIVO = "MEM60014"          # «Jeferson Moreno» (apellido mal registrado; es Forero)
CORREO_OBJETIVO = "jeferson@senaviacorp.com"
ROL_ACTUAL = "ROL60003"        # Full Admin
ROL_PROHIBIDO = "ROL60001"     # inactivo PERO con Allow *:* — jamas usarlo de destino

NOMBRE_ROL_NUEVO = "Revocado - sin acceso"
DESC_ROL_NUEVO = ("Rol terminal sin permisos y con Active=false. Contrato v8.0 num. 9.4: "
                  "acceso revocado tras la terminacion. No enlazar ningun permiso a este rol.")

# Los cinco Full Admin legitimos: si alguno deja de serlo, algo salio mal.
INTOCABLES = {
    "MEM60001": "Manuel Ramirez",
    "MEM60002": "Jagger Thornton",
    "MEM60004": "Kelley Ramirez",
    "MEM60010": "Allison Villamizar",
    "MEM60012": "Sebastian Navia",
}

APLICAR = False
TOKEN = None


def _contexto_ssl():
    """El Python de python.org en macOS no usa el llavero del sistema; certifi
    trae el mismo bundle de Mozilla y ya es dependencia del proyecto. Nunca se
    desactiva la verificacion: aqui viajan credenciales."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_SSL = _contexto_ssl()


def _peticion(metodo, ruta, cuerpo=None, token=None):
    url = f"{BASE}{ruta}"
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, method=metodo)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=45, context=_SSL) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        cuerpo_err = e.read().decode()
        try:
            return e.code, json.loads(cuerpo_err or "{}")
        except json.JSONDecodeError:
            return e.code, {"raw": cuerpo_err[:300]}
    except Exception as e:
        return 0, {"error": str(e)}


def paso(descripcion, metodo, ruta, cuerpo=None, censurar=None):
    """Ejecuta un cambio, o lo describe si estamos en dry run.

    `censurar`: claves del cuerpo que NUNCA se imprimen (contrasenas).
    Devuelve (ok, respuesta) — el ID del rol nuevo lo genera el servidor.
    """
    visible = dict(cuerpo) if cuerpo else None
    for k in (censurar or []):
        if visible and k in visible:
            visible[k] = "***"
    if not APLICAR:
        extra = f"  body={json.dumps(visible)}" if visible else ""
        print(f"   [DRY] {metodo} {ruta}{extra}")
        print(f"         -> {descripcion}")
        return True, {}
    codigo, respuesta = _peticion(metodo, ruta, cuerpo, TOKEN)
    ok = 200 <= codigo < 300
    print(f"   {'OK ' if ok else 'FALLO'} {codigo} {metodo} {ruta}")
    if not ok:
        print(f"      {json.dumps(respuesta)[:220]}")
    print(f"      -> {descripcion}")
    return ok, respuesta


def main():
    global APLICAR, TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true",
                    help="escribe de verdad en produccion (por defecto: dry run)")
    args = ap.parse_args()
    APLICAR = args.aplicar

    print(f"\nAPI: {BASE}")
    print("MODO: " + ("APLICAR (escribe en produccion)" if APLICAR
                      else "DRY RUN (no escribe nada)"))

    if APLICAR:
        print("\nCredenciales de un Full Admin (no se guardan ni se imprimen):")
        correo = input("  correo: ").strip()
        if correo.lower() == CORREO_OBJETIVO:
            sys.exit("no puedes ejecutar esto con la cuenta que vas a revocar")
        clave = getpass.getpass("  contrasena: ")
        codigo, datos = _peticion("POST", "/auth/login",
                                  {"Email_Address": correo, "Password": clave})
        clave = None
        if codigo == 0:
            sys.exit(f"no se pudo contactar con {BASE} — la peticion no llego a salir:\n"
                     f"   {json.dumps(datos)[:200]}")
        if codigo == 401:
            sys.exit("correo o contrasena incorrectos (401)")
        if codigo != 200 or "access_token" not in datos:
            sys.exit(f"login fallido ({codigo}): {json.dumps(datos)[:200]}")
        TOKEN = datos["access_token"]
        ud = datos.get("user_data") or {}
        rol = ud.get("role_detail") or {}
        print(f"  dentro como {ud.get('Member_Name')} — rol {rol.get('Name')}")
        if rol.get("Name") != "Full Admin":
            sys.exit("ese usuario no es Full Admin: role:create y member:update exigen serlo")

    # ── Estado de partida ────────────────────────────────────────────────────
    print("\n" + "=" * 74)
    print(f"PASO 0 — estado de partida de {OBJETIVO}")
    print("=" * 74)
    if APLICAR:
        cod, antes = _peticion("GET", f"/member/{OBJETIVO}", token=TOKEN)
        if cod != 200:
            sys.exit(f"no se pudo leer {OBJETIVO} ({cod}): {json.dumps(antes)[:200]}")
        print(f"   {antes.get('Member_Name')} <{antes.get('Email_Address')}> "
              f"rol={antes.get('ID_Role')}")
        if antes.get("ID_Role") != ROL_ACTUAL:
            print(f"   AVISO: esperaba {ROL_ACTUAL}, encontre {antes.get('ID_Role')}. "
                  f"Alguien ya lo toco; revisa antes de seguir.")
    else:
        print(f"   [DRY] GET /member/{OBJETIVO}")

    # ── Rol terminal ─────────────────────────────────────────────────────────
    print("\n" + "=" * 74)
    print("PASO 1 — crear el rol terminal (Active=false, CERO permisos)")
    print("=" * 74)
    ok, creado = paso(
        "rol sin permisos: PolicyEvaluator arranca en allowed=False, asi que deniega todo. "
        "Active=false ademas hace que /refresh devuelva 401 (REG-100)",
        "POST", "/role/",
        {"Name": NOMBRE_ROL_NUEVO, "Description": DESC_ROL_NUEVO, "Active": False})
    if not ok:
        sys.exit("no se pudo crear el rol; no sigo (no voy a dejar a medias la revocacion)")

    rol_nuevo = creado.get("ID_Role") if APLICAR else "ROL6000X-DRYRUN"
    if APLICAR and not rol_nuevo:
        sys.exit(f"el API no devolvio ID_Role: {json.dumps(creado)[:200]}")
    if rol_nuevo == ROL_PROHIBIDO:
        sys.exit(f"el rol creado colisiona con {ROL_PROHIBIDO} (Allow *:*). Aborto.")
    print(f"   rol destino: {rol_nuevo}")

    # ── Reasignacion + contrasena ────────────────────────────────────────────
    print("\n" + "=" * 74)
    print(f"PASO 2 — sacar a {OBJETIVO} de Full Admin y cerrarle el login")
    print("=" * 74)
    ok_rol, _ = paso(
        f"reasignar {OBJETIVO}: {ROL_ACTUAL} (Full Admin) -> {rol_nuevo}. "
        f"Pierde permisos en la SIGUIENTE peticion; las politicas se releen por request",
        "PATCH", f"/member/{OBJETIVO}", {"ID_Role": rol_nuevo})

    nueva = secrets.token_urlsafe(48)   # nadie la conoce, ni siquiera este proceso la guarda
    ok_pw, _ = paso(
        f"invalidar la contrasena de {OBJETIVO} (la fila NO se borra: hay purchase y "
        f"tlactivity apuntando, y el rastro sostiene los num. 9.3 y 6.6)",
        "PATCH", f"/member/{OBJETIVO}", {"Password": nueva}, censurar=["Password"])
    nueva = None

    if APLICAR and not (ok_rol and ok_pw):
        print("\n   AVISO: la revocacion quedo A MEDIAS. Revisa los fallos de arriba "
              "y vuelve a correr antes de dar nada por cerrado.")

    # ── Verificacion ─────────────────────────────────────────────────────────
    print("\n" + "=" * 74)
    print("PASO 3 — verificacion (no me fio de los 200)")
    print("=" * 74)
    if not APLICAR:
        print("   [DRY] se comprobaria: rol de MEM60014, Active del rol nuevo, "
              "sus permisos, y que los 5 Full Admin legitimos siguen en ROL60003")
        print("\nDRY RUN terminado. Nada se ha escrito. Para aplicar:")
        print("   python3 scripts/revocar_acceso_mem60014.py --aplicar\n")
        return

    fallos = []

    cod, despues = _peticion("GET", f"/member/{OBJETIVO}", token=TOKEN)
    rol_final = despues.get("ID_Role")
    print(f"   {OBJETIVO} rol = {rol_final}")
    if rol_final != rol_nuevo:
        fallos.append(f"{OBJETIVO} sigue en {rol_final}, esperaba {rol_nuevo}")

    cod, rdet = _peticion("GET", f"/role/{rol_nuevo}", token=TOKEN)
    activo = rdet.get("Active")
    permisos = rdet.get("permissions") or rdet.get("Permissions") or []
    print(f"   rol {rol_nuevo}: Active={activo}  permisos={len(permisos)}")
    if activo is not False:
        fallos.append(f"el rol {rol_nuevo} NO quedo inactivo (Active={activo}): "
                      f"sin eso /refresh no le corta la sesion")
    if permisos:
        fallos.append(f"el rol {rol_nuevo} tiene {len(permisos)} permisos enlazados; "
                      f"debe tener CERO")

    print("   Full Admin legitimos:")
    for mid, nombre in sorted(INTOCABLES.items()):
        c, m = _peticion("GET", f"/member/{mid}", token=TOKEN)
        r = m.get("ID_Role") if c == 200 else f"<error {c}>"
        marca = "ok" if r == ROL_ACTUAL else "REVISAR"
        print(f"     {marca:8} {mid} {nombre:20} rol={r}")
        if r != ROL_ACTUAL:
            fallos.append(f"{mid} ({nombre}) quedo en {r}, deberia seguir en {ROL_ACTUAL}")

    print("\n" + "=" * 74)
    if fallos:
        print("REVOCACION INCOMPLETA — no la des por cerrada:")
        for f in fallos:
            print(f"   - {f}")
        sys.exit(1)
    print("REVOCACION COMPLETA Y VERIFICADA")
    print(f"   {OBJETIVO} sin permisos y sin contrasena valida.")
    print("   Su sesion viva caduca al expirar el access token "
          "(ACCESS_TOKEN_EXPIRES_MIN, 60 min por defecto);")
    print("   /refresh ya le devuelve 401 porque el rol esta inactivo.")
    print("=" * 74 + "\n")


if __name__ == "__main__":
    main()
