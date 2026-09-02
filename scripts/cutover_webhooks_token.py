#!/usr/bin/env python3
"""Cutover del token de los webhooks de Podio, guiado por el CENSO.

  DRY RUN (por defecto, no escribe nada):
    python3 scripts/cutover_webhooks_token.py --censo ~/outputs/gqm-cierre-accesos/censo.json

  CANARY — una sola app, un solo evento:
    python3 scripts/cutover_webhooks_token.py --censo … --solo PTL/2024 --eventos item.update --aplicar

  EL RESTO:
    python3 scripts/cutover_webhooks_token.py --censo … --aplicar

  COMPROBAR QUE SE ACTIVARON (y pedir la verificacion a los que no):
    python3 scripts/cutover_webhooks_token.py --registro creados.json --verificar-activos
    python3 scripts/cutover_webhooks_token.py --registro creados.json --verificar-activos --pedir-verificacion --aplicar

  ROLLBACK — borra EXACTAMENTE los hooks que este script creo:
    python3 scripts/cutover_webhooks_token.py --registro creados.json --revertir --aplicar

POR QUE VA POR EL API Y NO POR PODIO DIRECTAMENTE
--------------------------------------------------
El `.env` de esta maquina es `APP_ENV=test` con `PUBLIC_URL=http://localhost:8000`
y credenciales TAP. Un registro lanzado desde aqui crearia hooks en apps de
PRUEBA apuntando a localhost, devolveria 200, y dejaria los 48 reales intactos.
Es el modo de fallo mas enganoso de esta tarea. Por eso todo pasa por los
endpoints de produccion, que usan el PUBLIC_URL y el token del servidor.

POR QUE GUIADO POR CENSO
------------------------
`/register` sin `?events=` crea SIEMPRE los 4 eventos, porque
`FILE_CHANGE_APP_TYPES` contiene las 7 familias. Las apps reales no estan asi:
PMC, QID/2024, PTL/2024 y PAR/2024 tienen 3, sin `file.change`. Registrar sin
acotar convertiria una rotacion de token en un cambio de topologia, y empezaria
a subir adjuntos de años cerrados a Cloudinary.

Y las apps de 2023 tienen CERO hooks a proposito: darles hooks le concederia a
Podio, por primera vez, la capacidad de borrar en cascada sus 2.212 jobs via
`item.delete`. El censo las trae a cero, asi que este script no las toca.

SE PARSEA EL CUERPO, NUNCA EL CODIGO HTTP
------------------------------------------
`/register` y `/clear` responden 200 aunque todo falle (`AdminHooks.py`: no
miran `errors` ni `success`), y `register` se traga los 429.
"""
import argparse
import getpass
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("GQM_API_URL", "https://gqm-api.vercel.app").rstrip("/")


def _contexto_ssl():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_SSL = _contexto_ssl()


def _peticion(metodo, ruta, cuerpo=None, token=None):
    req = urllib.request.Request(
        f"{BASE}{ruta}",
        data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
        method=metodo)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=90, context=_SSL) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        crudo = e.read().decode()
        try:
            return e.code, json.loads(crudo or "{}")
        except json.JSONDecodeError:
            return e.code, {"raw": crudo[:300]}
    except Exception as e:
        return 0, {"error": str(e)}


def _login():
    print(f"\nAPI: {BASE}")
    print("\nCredenciales de un Full Admin (no se guardan ni se imprimen):")
    correo = input("  correo: ").strip()
    clave = getpass.getpass("  contrasena: ")
    cod, datos = _peticion("POST", "/auth/login",
                           {"Email_Address": correo, "Password": clave})
    del clave
    if cod == 0:
        sys.exit(f"no se pudo contactar con {BASE}: {json.dumps(datos)[:200]}")
    if cod == 401:
        sys.exit("correo o contrasena incorrectos (401)")
    if cod != 200 or "access_token" not in datos:
        sys.exit(f"login fallido ({cod}): {json.dumps(datos)[:200]}")
    ud = datos.get("user_data") or {}
    rol = (ud.get("role_detail") or {}).get("Name")
    print(f"  dentro como {ud.get('Member_Name')} — rol {rol}")
    if rol != "Full Admin":
        sys.exit("ese usuario no es Full Admin: /admin/webhooks exige admin:sync")
    return datos["access_token"]


def _grupos_del_censo(ruta, solo=None, eventos=None):
    """(app, anio) -> lista de eventos, tal y como estan HOY en produccion."""
    censo = json.load(open(ruta, encoding="utf-8"))["censo"]
    grupos = {}
    for h in censo:
        grupos.setdefault((h["app"], h["anio"]), []).append(h["evento"])

    # Orden estable y sin duplicados.
    orden = ["item.create", "item.update", "item.delete", "file.change"]
    grupos = {k: sorted(set(v), key=orden.index) for k, v in grupos.items()}

    if solo:
        app, _, anio = solo.partition("/")
        clave = (app.upper(), int(anio) if anio else None)
        if clave not in grupos:
            sys.exit(f"--solo {solo}: esa app-año no esta en el censo "
                     f"(las que hay: {sorted(str(k) for k in grupos)})")
        grupos = {clave: grupos[clave]}

    if eventos:
        pedidos = [e.strip() for e in eventos.split(",") if e.strip()]
        for clave, tiene in grupos.items():
            fuera = [e for e in pedidos if e not in tiene]
            if fuera:
                sys.exit(f"--eventos {fuera} no existen hoy en {clave}: "
                         f"el cutover NO cambia la topologia")
        grupos = {k: pedidos for k in grupos}

    return grupos


def _ruta(app, anio, sufijo="", extra=""):
    q = f"?year={anio}" if anio else ""
    if extra:
        q = (q + "&" if q else "?") + extra
    # Sin sufijo NO se deja la barra: `/admin/webhooks/PTL/?year=2024` provoca
    # el redirect 308 de strict_slashes, y arrastrar la cabecera Authorization
    # por un redirect falla en produccion y no en pruebas.
    base = f"/admin/webhooks/{app}/{sufijo}" if sufijo else f"/admin/webhooks/{app}"
    return f"{base}{q}"


# ── REGISTRAR ───────────────────────────────────────────────────────────────

def registrar(token, grupos, aplicar, ruta_registro):
    total = sum(len(v) for v in grupos.values())
    print(f"\n{'APLICANDO' if aplicar else 'DRY RUN'} — "
          f"{len(grupos)} app-años, {total} hooks a crear\n")

    creados, fallos = [], []
    for (app, anio), eventos in sorted(grupos.items(), key=lambda x: str(x[0])):
        etiqueta = f"{app}/{anio}" if anio else app
        ruta = _ruta(app, anio, "register", "events=" + ",".join(eventos))
        if not aplicar:
            print(f"  {etiqueta:12} {len(eventos)} → POST {ruta}")
            continue

        cod, resp = _peticion("POST", ruta, token=token)
        # EL CUERPO, no el codigo: /register responde 200 aunque todo falle.
        if cod != 200 or not isinstance(resp, dict):
            print(f"  {etiqueta:12} ❌ HTTP {cod}: {json.dumps(resp)[:160]}")
            fallos.append((etiqueta, cod, resp))
            continue

        nuevos = resp.get("created") or []
        errores = resp.get("errors") or []
        omitidos = resp.get("skipped") or []
        for h in nuevos:
            hid = h.get("hook_id") if isinstance(h, dict) else h
            creados.append({"app": app, "anio": anio, "hook_id": hid})

        marca = "❌" if errores else "✅"
        print(f"  {etiqueta:12} {marca} creados={len(nuevos)} "
              f"ya_existian={len(omitidos)} errores={len(errores)}"
              f"  target={resp.get('target')}")
        for e in errores:
            print(f"       ERROR {e}")
            fallos.append((etiqueta, "cuerpo", e))

    if aplicar and creados:
        previos = []
        if os.path.exists(ruta_registro):
            previos = json.load(open(ruta_registro, encoding="utf-8")).get("creados", [])
        vistos, union = set(), []
        for h in previos + creados:
            if h["hook_id"] not in vistos:
                vistos.add(h["hook_id"])
                union.append(h)
        with open(ruta_registro, "w", encoding="utf-8") as f:
            json.dump({"creados": union}, f, indent=2, ensure_ascii=False)
        print(f"\n  registro -> {ruta_registro}  ({len(union)} hooks)")
        print("  ESTE FICHERO ES EL CAMINO DE VUELTA. No lo borres.")

    print(f"\n  creados: {len(creados)}   fallos: {len(fallos)}")
    return 1 if fallos else 0


# ── VERIFICAR QUE SE ACTIVARON ──────────────────────────────────────────────

def verificar_activos(token, ruta_registro, pedir, aplicar):
    """Un hook nace `inactive` y NO dispara jamas hasta que Podio le manda el
    hook.verify. Que lo mande solo se midio en dev, nunca en produccion."""
    creados = json.load(open(ruta_registro, encoding="utf-8"))["creados"]
    por_app = {}
    for h in creados:
        por_app.setdefault((h["app"], h["anio"]), []).append(h["hook_id"])

    inactivos, activos, perdidos, sin_token = [], 0, [], []
    for (app, anio), ids in sorted(por_app.items(), key=lambda x: str(x[0])):
        etiqueta = f"{app}/{anio}" if anio else app
        cod, resp = _peticion("GET", _ruta(app, anio), token=token)
        if cod != 200 or not isinstance(resp, list):
            print(f"  {etiqueta:12} NO CONSULTABLE ({cod})  <-- NO es 'limpia'")
            perdidos.append(etiqueta)
            continue
        info = {h.get("hook_id"): (h.get("status"), h.get("url") or "") for h in resp}
        for hid in ids:
            st, url = info.get(hid, (None, ""))

            # EL ORACULO DEL TOKEN. El API redacta a *** solo el token VIGENTE,
            # asi que una URL que acabe en *** demuestra que el token con el que
            # se registro el hook es el mismo que hay desplegado. Si acaba en
            # otra cosa, el hook se registro sin token o con uno viejo — y eso
            # es indistinguible de un hook sano hasta que deja de entregar.
            redactada = url.rstrip("/").endswith("***")
            if not redactada:
                print(f"  {etiqueta:12} hook_id={hid} 🔴 URL SIN TOKEN VIGENTE: {url}")
                sin_token.append((app, anio, hid, url))

            if st == "active":
                activos += 1
                if redactada:
                    print(f"  {etiqueta:12} hook_id={hid} ✅ active  {url}")
            else:
                print(f"  {etiqueta:12} hook_id={hid} ⏳ status={st}  {url}")
                inactivos.append((app, anio, hid))

    print(f"\n  activos: {activos}   NO activos: {len(inactivos)}   "
          f"sin el token vigente: {len(sin_token)}   "
          f"apps no consultables: {len(perdidos)}")
    if sin_token:
        print("  🔴 Hay hooks que NO llevan el token vigente. Entregarian 403 en"
              "\n     cuanto se retire la gracia. Borralos y vuelve a registrarlos.")

    if inactivos and pedir:
        print(f"\n  {'Pidiendo' if aplicar else 'DRY RUN — pediria'} la verificacion "
              f"de {len(inactivos)} hooks")
        for app, anio, hid in inactivos:
            if not aplicar:
                print(f"    POST {_ruta(app, anio, f'verify/{hid}')}")
                continue
            cod, resp = _peticion("POST", _ruta(app, anio, f"verify/{hid}"), token=token)
            ok = isinstance(resp, dict) and resp.get("success")
            print(f"    hook_id={hid}: {'📨 solicitada' if ok else f'❌ {cod} {resp}'}")

    if perdidos:
        print("\n  ⚠️ Hay apps que no se pudieron leer: el recuento de arriba "
              "NO es completo.")
    return 1 if (inactivos or perdidos or sin_token) else 0


# ── ROLLBACK ────────────────────────────────────────────────────────────────

def revertir(token, ruta_registro, aplicar, ids=None):
    """Borra EXACTAMENTE los hooks que creo este script. Los hooks nuevos los
    creo la aplicacion, asi que el app token si puede borrarlos; los 48 viejos
    los creo una cuenta de usuario y darian 403."""
    todos = json.load(open(ruta_registro, encoding="utf-8"))["creados"]
    if ids:
        creados = [h for h in todos if h["hook_id"] in ids]
        desconocidos = ids - {h["hook_id"] for h in todos}
        if desconocidos:
            sys.exit(f"--ids {sorted(desconocidos)} no estan en el registro: "
                     f"borrar a ciegas un hook que no creo este script NO.")
    else:
        creados = todos

    print(f"\n{'BORRANDO' if aplicar else 'DRY RUN'} — {len(creados)} de "
          f"{len(todos)} hooks del registro\n")
    fallos, borrados = [], []
    for h in creados:
        ruta = _ruta(h["app"], h["anio"], f"hook/{h['hook_id']}")
        if not aplicar:
            print(f"  DELETE {ruta}")
            continue
        cod, resp = _peticion("DELETE", ruta, token=token)
        ok = isinstance(resp, dict) and resp.get("success")
        print(f"  hook_id={h['hook_id']}: {'🗑️ borrado' if ok else f'❌ {cod} {resp}'}")
        (borrados if ok else fallos).append(h["hook_id"])

    # El registro deja de nombrar lo que ya no existe: es el inventario de la
    # generacion nueva, y un inventario que miente es peor que no tenerlo.
    if aplicar and borrados:
        quedan = [h for h in todos if h["hook_id"] not in set(borrados)]
        with open(ruta_registro, "w", encoding="utf-8") as f:
            json.dump({"creados": quedan}, f, indent=2, ensure_ascii=False)
        print(f"\n  registro actualizado: quedan {len(quedan)} hooks")

    if fallos:
        print(f"\n  ❌ {len(fallos)} no se pudieron borrar: {fallos}")
        print("  Borralos desde la UI de Podio (Modify template -> Webhooks).")
    return 1 if fallos else 0


def _autochequeo():
    """La agrupacion por censo es lo unico con logica de verdad aqui: si se
    rompe, el cutover cambia la topologia sin avisar. No pide credenciales."""
    import tempfile
    censo = {"censo": [
        {"app": "QID", "anio": 2026, "evento": "file.change"},
        {"app": "QID", "anio": 2026, "evento": "item.create"},
        {"app": "QID", "anio": 2024, "evento": "item.delete"},
        {"app": "QID", "anio": 2024, "evento": "item.create"},
        {"app": "PMC", "anio": None, "evento": "item.update"},
    ]}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(censo, f)
        ruta = f.name

    fallos = 0

    def _check(cond, msg):
        nonlocal fallos
        if not cond:
            fallos += 1
            print(f"  FALLO: {msg}")

    g = _grupos_del_censo(ruta)
    _check(len(g) == 3, f"esperaba 3 app-años, hay {len(g)}")
    # El orden de los eventos es el canonico, no el del censo.
    _check(g[("QID", 2026)] == ["item.create", "file.change"],
           f"QID/2026 mal ordenado: {g[('QID', 2026)]}")
    # Y 2024 NO recibe file.change: es lo que impide cambiar la topologia.
    _check("file.change" not in g[("QID", 2024)], "QID/2024 no debe llevar file.change")
    _check(g[("PMC", None)] == ["item.update"], "PMC mal agrupada")

    g = _grupos_del_censo(ruta, solo="QID/2024")
    _check(list(g) == [("QID", 2024)], f"--solo no acoto: {list(g)}")

    g = _grupos_del_censo(ruta, solo="PMC")
    _check(list(g) == [("PMC", None)], "--solo sin año debe funcionar para las estaticas")

    # Pedir un evento que la app NO tiene hoy debe abortar, no crearlo.
    try:
        _grupos_del_censo(ruta, solo="QID/2024", eventos="file.change")
        fallos += 1
        print("  FALLO: --eventos permitio un evento que no existe en el censo")
    except SystemExit:
        pass

    os.unlink(ruta)
    print(f"autochequeo: 7 comprobaciones, {fallos} fallos")
    return 1 if fallos else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--censo", help="censo JSON de listar_hooks_produccion.py")
    ap.add_argument("--registro", default="cutover-hooks-creados.json",
                    help="donde se anotan los hook_id creados (camino de vuelta)")
    ap.add_argument("--solo", metavar="APP[/AÑO]", help="una sola app-año (canary)")
    ap.add_argument("--eventos", help="acota los eventos; deben existir ya en el censo")
    ap.add_argument("--verificar-activos", action="store_true")
    ap.add_argument("--pedir-verificacion", action="store_true",
                    help="a los que sigan inactive, pedirle a Podio el hook.verify")
    ap.add_argument("--revertir", action="store_true")
    ap.add_argument("--ids", help="acota --revertir a estos hook_id (coma). "
                                  "Deben estar en el registro.")
    ap.add_argument("--aplicar", action="store_true",
                    help="sin esto no se escribe NADA")
    ap.add_argument("--autochequeo", action="store_true",
                    help="prueba la agrupacion por censo y sale")
    args = ap.parse_args()

    if args.autochequeo:
        return _autochequeo()

    # El login SOLO cuando se va a hablar con el API. Un dry run no escribe
    # nada y no debe pedir credenciales: si las pide, no se usa.
    #
    # --verificar-activos si necesita leer, asi que ahi tambien hace falta.
    if args.revertir or args.verificar_activos:
        if not os.path.exists(args.registro):
            sys.exit(f"no existe el registro {args.registro}")
        if args.revertir:
            ids = ({int(x) for x in args.ids.split(",") if x.strip()}
                   if args.ids else None)
            return revertir(_login() if args.aplicar else None,
                            args.registro, args.aplicar, ids)
        return verificar_activos(_login(), args.registro,
                                 args.pedir_verificacion, args.aplicar)

    if not args.censo:
        sys.exit("hace falta --censo (o --revertir / --verificar-activos)")
    grupos = _grupos_del_censo(args.censo, args.solo, args.eventos)
    return registrar(_login() if args.aplicar else None,
                     grupos, args.aplicar, args.registro)


if __name__ == "__main__":
    sys.exit(main() or 0)
