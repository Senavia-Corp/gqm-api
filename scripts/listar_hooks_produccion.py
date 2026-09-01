#!/usr/bin/env python3
"""Enumera los webhooks de Podio de PRODUCCION. SOLO LECTURA.

  python3 scripts/listar_hooks_produccion.py
  python3 scripts/listar_hooks_produccion.py --md informe.md

No hace ni una escritura: solo POST /auth/login y GET /admin/webhooks/<app>.

POR QUE VA POR EL API Y NO POR PODIO DIRECTAMENTE
--------------------------------------------------
Los APP_TOKEN de las apps de produccion NO estan (ni deben estar) en el .env de
esta maquina: el .env local es APP_ENV=test y solo trae las TAP. La API de
produccion ya tiene esas credenciales, asi que se le pregunta a ella. Asi no se
saca ningun secreto de produccion al portatil.

GET /admin/webhooks/<app> exige `admin:sync` (protect_blueprint en main.py:196),
o sea Full Admin. Pide correo y contrasena por stdin; no se guardan ni se
imprimen ni viajan por argumentos.

QUE BUSCA
---------
1. Hooks hacia un dominio AJENO a SENAVIA (api.taskipos.com, ngrok, devtunnels).
2. Hooks SIN token en la ruta. Con PODIO_WEBHOOK_TOKEN configurado en produccion
   —lo esta: es una de las variables que abortan el arranque— un hook sin token
   recibe 403 permanente en _validate_podio_webhook_token (Webhook_bp.py:96).
   No es solo un agujero: es sincronizacion MUERTA en silencio.
3. Hooks en estado distinto de `active`: un hook `inactive` no dispara jamas.
"""
import argparse
import getpass
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("GQM_API_URL", "https://gqm-api.vercel.app").rstrip("/")

# Las 16 apps de produccion: 4 estaticas + 3 tipos de job x 4 años.
ESTATICAS = ["CLI", "SUBC", "PMC", "BDEP"]
JOBS = ["QID", "PTL", "PAR"]
ANIOS = [2023, 2024, 2025, 2026]

# Todo lo que no sea uno de estos hosts es ajeno y hay que mirarlo.
HOSTS_PROPIOS = ("gqm-api.vercel.app", "gqm-api-dev.vercel.app", "gqmconnect.com")


def _contexto_ssl():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_SSL = _contexto_ssl()


def _peticion(metodo, ruta, cuerpo=None, token=None):
    req = urllib.request.Request(f"{BASE}{ruta}",
                                 data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
                                 method=metodo)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=45, context=_SSL) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        cuerpo_err = e.read().decode()
        try:
            return e.code, json.loads(cuerpo_err or "{}")
        except json.JSONDecodeError:
            return e.code, {"raw": cuerpo_err[:300]}
    except Exception as e:
        return 0, {"error": str(e)}


def _censura(url):
    """El API ya redacta el token vigente a ***. Si un hook lleva otro token
    (uno viejo), saldria EN CLARO: lo tapo yo tambien. Un segmento hex largo al
    final de la ruta solo puede ser un token."""
    return re.sub(r"/[0-9a-f]{24,}(?=/|$)", "/<TOKEN-REDACTADO>", url or "")


def _sin_token(url):
    """True si la ruta no acaba en un segmento de token."""
    ruta = (url or "").split("?")[0].rstrip("/")
    return not ruta.endswith("***") and not re.search(r"/[0-9a-f]{24,}$", ruta)


def _ajeno(url):
    host = re.sub(r"^https?://", "", url or "").split("/")[0].lower()
    return host and not any(host == p or host.endswith("." + p) for p in HOSTS_PROPIOS)


def _autochequeo():
    """La clasificacion de URLs es lo unico con logica de verdad aqui: si se
    rompe, el informe dice 'limpio' sobre hooks que no lo estan."""
    T = "d6e3b17eb0656fb3d9aba7d50a72595080a80da0037195d2"
    casos = [
        (f"https://gqm-api.vercel.app/webhook/podio/jobs/QID/2026/{T}", False, False),
        ("https://gqm-api.vercel.app/webhook/podio/jobs/QID/2026/***", False, False),
        ("https://gqm-api.vercel.app/webhook/podio/jobs/QID/2026", False, True),
        ("https://gqm-api-dev.vercel.app/webhook/podio/others/relations/CLI/***", False, False),
        (f"https://api.taskipos.com/webhook/podio/jobs/QID/2026/{T}", True, False),
        ("https://api.taskipos.com/webhook/podio/jobs/QID/2026", True, True),
        ("https://abc123.ngrok-free.app/webhook/podio/others/CLI", True, True),
        ("https://xyz.devtunnels.ms/webhook/podio/jobs/PTL/2025", True, True),
        # sufijo enganoso: NO basta con `in`, el host tiene que coincidir o ser subdominio
        ("https://evil-gqm-api.vercel.app.attacker.com/webhook/x", True, True),
    ]
    fallos = 0
    for url, esp_aj, esp_st in casos:
        aj, st = _ajeno(url), _sin_token(url)
        if (aj, st) != (esp_aj, esp_st):
            fallos += 1
            print(f"  FALLO {url}\n        ajeno={aj} (esperaba {esp_aj})  "
                  f"sin_token={st} (esperaba {esp_st})")
    limpio = _censura(f"https://api.taskipos.com/webhook/podio/jobs/QID/2026/{T}")
    if T in limpio:
        fallos += 1; print("  FALLO: la censura deja escapar el token")
    if "taskipos" not in limpio:
        fallos += 1; print("  FALLO: la censura tapa el host, que es lo que hay que ver")
    print(f"autochequeo: {len(casos) + 2} comprobaciones, {fallos} fallos")
    return 1 if fallos else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", metavar="RUTA", help="escribe el informe en markdown")
    ap.add_argument("--censo", metavar="RUTA",
                    help="persiste el censo en JSON: es el ORACULO del cutover")
    ap.add_argument("--autochequeo", action="store_true",
                    help="prueba la clasificacion de URLs y sale (no pide credenciales)")
    args = ap.parse_args()

    if args.autochequeo:
        return _autochequeo()

    print(f"\nAPI: {BASE}    (SOLO LECTURA: login + GETs)")
    print("\nCredenciales de un Full Admin (no se guardan ni se imprimen):")
    correo = input("  correo: ").strip()
    clave = getpass.getpass("  contrasena: ")
    cod, datos = _peticion("POST", "/auth/login",
                           {"Email_Address": correo, "Password": clave})
    clave = None
    if cod == 0:
        sys.exit(f"no se pudo contactar con {BASE}: {json.dumps(datos)[:200]}")
    if cod == 401:
        sys.exit("correo o contrasena incorrectos (401)")
    if cod != 200 or "access_token" not in datos:
        sys.exit(f"login fallido ({cod}): {json.dumps(datos)[:200]}")
    token = datos["access_token"]
    ud = datos.get("user_data") or {}
    rol = (ud.get("role_detail") or {}).get("Name")
    print(f"  dentro como {ud.get('Member_Name')} — rol {rol}")
    if rol != "Full Admin":
        sys.exit("ese usuario no es Full Admin: /admin/webhooks exige admin:sync")

    objetivos = [(a, None) for a in ESTATICAS] + [(t, y) for t in JOBS for y in ANIOS]

    filas, ajenos, sin_token, inactivos, no_consultables = [], [], [], [], []
    dueno_ajeno, censo = [], []

    print(f"\nConsultando {len(objetivos)} apps de produccion...\n")
    for app_type, anio in objetivos:
        ruta = f"/admin/webhooks/{app_type}" + (f"?year={anio}" if anio else "")
        etiqueta = f"{app_type}/{anio}" if anio else app_type
        cod, resp = _peticion("GET", ruta, token=token)

        if cod != 200 or not isinstance(resp, list):
            detalle = (resp.get("detail") or resp.get("error") or json.dumps(resp))[:110] \
                if isinstance(resp, dict) else str(resp)[:110]
            print(f"  {etiqueta:12} NO CONSULTABLE ({cod}) {detalle}")
            no_consultables.append((etiqueta, cod, detalle))
            continue

        if not resp:
            print(f"  {etiqueta:12} 0 hooks")
            filas.append((etiqueta, 0, 0, 0, 0))
            continue

        n_aj = n_st = n_inact = 0
        print(f"  {etiqueta:12} {len(resp)} hooks")
        for h in resp:
            url = h.get("url") or ""
            hid, tipo, estado = h.get("hook_id"), h.get("type"), h.get("status")
            cb = (h.get("created_by") or {}).get("type")
            if cb and cb != "app":
                dueno_ajeno.append({"app": etiqueta, "hook_id": hid, "type": tipo,
                                    "created_by": h.get("created_by"),
                                    "created_via": h.get("created_via")})
            censo.append({"app": app_type, "anio": anio, "evento": tipo, "hook_id": hid,
                          "status": estado, "url": _censura(url), "created_by": cb,
                          # El objeto ENTERO, no solo el `type`. Con el type se
                          # sabe que lo creo una persona; con el id se sabe
                          # CUAL, que es lo que decide la autoria de los 48.
                          "created_by_detalle": h.get("created_by"),
                          "created_via": h.get("created_via"),
                          "created_on": h.get("created_on")})
            marcas = []
            if _ajeno(url):
                marcas.append("AJENO"); n_aj += 1
                ajenos.append({"app": etiqueta, "hook_id": hid, "type": tipo,
                               "status": estado, "url": _censura(url)})
            if _sin_token(url):
                marcas.append("SIN-TOKEN"); n_st += 1
                sin_token.append({"app": etiqueta, "hook_id": hid, "type": tipo,
                                  "status": estado, "url": _censura(url)})
            if estado != "active":
                marcas.append(f"status={estado}"); n_inact += 1
                inactivos.append({"app": etiqueta, "hook_id": hid, "type": tipo,
                                  "status": estado})
            sufijo = ("   <<< " + " ".join(marcas)) if marcas else ""
            print(f"       hook_id={hid} {tipo} {estado} {_censura(url)}{sufijo}")
        filas.append((etiqueta, len(resp), n_aj, n_st, n_inact))

    # ── Resumen ──────────────────────────────────────────────────────────────
    total = sum(f[1] for f in filas)
    print("\n" + "=" * 74)
    print(f"RESUMEN — {len(filas)} apps consultadas, {total} hooks")
    print("=" * 74)
    print(f"  hacia dominio AJENO a SENAVIA : {len(ajenos)}")
    print(f"  SIN token en la ruta (403)    : {len(sin_token)}")
    print(f"  en estado distinto de active  : {len(inactivos)}")
    if no_consultables:
        print(f"  apps NO consultables          : {len(no_consultables)}  <-- NO son 'limpias'")
        for et, c, d in no_consultables:
            print(f"      {et}: {c} {d}")

    if ajenos:
        print("\n  HOOKS AJENOS (borrar por hook_id: /admin/webhooks/<app>/clear NO los toca,")
        print("  fuerza only_own=True y solo borra los que apuntan a PUBLIC_URL):")
        for h in ajenos:
            print(f"      {h['app']} hook_id={h['hook_id']} {h['type']} {h['url']}")

    if sin_token:
        print(f"\n  {len(sin_token)} hooks SIN token: con PODIO_WEBHOOK_TOKEN configurado")
        print("  reciben 403 permanente — esa sincronizacion esta MUERTA, no solo abierta.")

    # PRECONDICION DEL CUTOVER: quien creo el hook decide si el app token puede
    # borrarlo. Si lo creo una cuenta de USUARIO, DELETE /hook/<id> con el app
    # token devuelve 403 y `/clear` responde 200 con success:false dentro del
    # cuerpo — es decir, parece que borro y no borro nada.
    print()
    if dueno_ajeno:
        print(f"  ⚠️  {len(dueno_ajeno)} hooks NO los creo la app (created_by.type != 'app').")
        print("      El borrado por API dara 403: hay que borrarlos desde la UI de Podio")
        print("      (Modify template -> Webhooks, app por app).")
        for h in dueno_ajeno[:6]:
            print(f"      {h['app']} hook_id={h['hook_id']} created_by={h['created_by']}")
        if len(dueno_ajeno) > 6:
            print(f"      … y {len(dueno_ajeno) - 6} mas")
    else:
        print("  created_by = 'app' en todos: el borrado por API es viable.")

    if args.md:
        with open(args.md, "w", encoding="utf-8") as f:
            f.write("# Hooks de Podio en produccion\n\n")
            f.write(f"Enumerado contra `{BASE}` (solo lectura). "
                    f"{len(filas)} apps, {total} hooks.\n\n")
            f.write("| App | Hooks | Ajenos | Sin token | No activos |\n|---|---|---|---|---|\n")
            for et, n, a, s, i in filas:
                f.write(f"| {et} | {n} | {a} | {s} | {i} |\n")
            for titulo, lista in (("Hooks hacia dominio ajeno", ajenos),
                                  ("Hooks sin token en la ruta", sin_token),
                                  ("Hooks no activos", inactivos),
                                  ("Hooks NO creados por la app", dueno_ajeno)):
                f.write(f"\n## {titulo} ({len(lista)})\n\n")
                f.write("```json\n" + json.dumps(lista, indent=2, ensure_ascii=False) + "\n```\n")
            if no_consultables:
                f.write(f"\n## Apps NO consultables ({len(no_consultables)})\n\n")
                f.write("No se pudieron leer: **no cuentan como limpias**.\n\n")
                for et, c, d in no_consultables:
                    f.write(f"- `{et}` — HTTP {c}: {d}\n")
        print(f"\n  informe -> {args.md}")

    if args.censo:
        with open(args.censo, "w", encoding="utf-8") as f:
            json.dump({"apps": len(filas), "hooks": total, "censo": censo}, f,
                      indent=2, ensure_ascii=False)
        print(f"  censo  -> {args.censo}  ({total} hooks)")
        print("  Este fichero es el ORACULO del cutover: el censo final debe ser")
        print("  identico a este salvo por el token. Guardalo antes de tocar nada.")

    print()
    if ajenos:
        sys.exit(1)


if __name__ == "__main__":
    sys.exit(main() or 0)
