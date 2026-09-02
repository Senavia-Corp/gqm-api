#!/usr/bin/env python3
"""Vuelca los campos crudos de UN item de Podio. SOLO LECTURA.

  python3 scripts/leer_item_podio.py 3304340068 --tipo PAR --anio 2026
  python3 scripts/leer_item_podio.py 3304340068 --tipo PAR --anio 2026 --json reports/item.json
  python3 scripts/leer_item_podio.py --autochequeo

No hace ni una escritura: solo POST /auth/login y GET /admin/podio/parity.

POR QUE VA POR EL API Y NO POR PODIO DIRECTAMENTE
--------------------------------------------------
Mismo motivo que `listar_hooks_produccion.py`: los APP_TOKEN de las apps de
produccion NO estan en el .env de esta maquina (es APP_ENV=test y solo trae las
TAP). La API de produccion ya los tiene. Asi no se saca ningun secreto al
portatil. Ademas `parity` construye el servicio con
`podio_jobs_router.get_readonly_service(...)`, que rechaza escrituras pase lo
que pase.

POR QUE `parity` Y NO UN ENDPOINT NUEVO
---------------------------------------
No hay ruta que lea un item suelto, pero `GET /admin/podio/parity` con
`enumerar=true&campos=true` ya devuelve, por cada item de la app-año, sus campos
`money/number/calculation/progress/category/date` con `type` y `values` sin pasar
por el mapeador (Paridad.py:88 `_campos_crudos`). Es decir: ya existe lo que hace
falta, y anadir un endpoint solo para esto seria superficie nueva en produccion
por nada. Cuesta enumerar la app entera — PAR/2026 son 201 items, una sola
pagina de 500 — a cambio de no desplegar nada.

QUE CONTESTA
------------
Para que casilla `tech-N-*` sirve la respuesta hay que saber su `type`:

  * `calculation` -> Podio la calcula sola (tipicamente sumando los POs
    enlazados). No se puede escribir NI a mano NI por API: lo que se arregla son
    los enlaces, no la casilla.
  * `number` / `money` -> alguien escribio ese valor. Se puede corregir desde la
    UI, y conviene saber quien lo puso antes de pisarlo.

`--autochequeo` prueba la extraccion contra payloads de mentira y sale sin pedir
credenciales ni tocar la red.
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


def _peticion(metodo, ruta, cuerpo=None, token=None, timeout=280):
    req = urllib.request.Request(
        f"{BASE}{ruta}",
        data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
        method=metodo)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        cuerpo_err = e.read().decode()
        try:
            return e.code, json.loads(cuerpo_err or "{}")
        except json.JSONDecodeError:
            return e.code, {"raw": cuerpo_err[:300]}
    except Exception as e:
        return 0, {"error": str(e)}


def buscar_item(filas, item_id):
    """Encuentra `item_id` entre las filas de /parity. Devuelve el item o None.

    Se compara como string a proposito: Podio da el item_id como entero y la
    respuesta lo serializa como string segun por donde pase. Comparar tipos
    distintos daria 'no encontrado' sobre un item que si esta.
    """
    objetivo = str(item_id)
    for fila in filas or []:
        for item in ((fila.get("podio") or {}).get("items") or []):
            if str(item.get("item_id")) == objetivo:
                return item
    return None


def campos_tech(campos):
    """Los campos de slot de tecnico, ordenados. `campos` es {external_id: {...}}.

    Filtra por prefijo `tech-` y no por una lista fija de external_id porque los
    nombres cambian entre PAR/PTL/QID y una lista quedaria desfasada en silencio.
    """
    return sorted((eid, meta) for eid, meta in (campos or {}).items()
                  if eid.startswith("tech-"))


def es_calculado(meta):
    return (meta or {}).get("type") == "calculation"


def _autochequeo():
    """Lo unico con logica aqui es la extraccion; si se rompe, el informe dice
    'no encontrado' sobre un item que si estaba, o se calla el tipo del campo."""
    filas = [
        {"podio": {"items": [{"item_id": 111, "campos": {}}]}},
        {"podio": {"items": [
            {"item_id": 3304340068, "campos": {
                "tech-1-ptl-original-pricing": {"type": "calculation", "values": [{"value": "440.0000"}]},
                "tech-2-ptl-original-pricing": {"type": "number", "values": [{"value": "220.0000"}]},
                "otro-campo": {"type": "number", "values": []}}}]}},
        {"podio": {}},
    ]
    fallos = 0

    def check(cond, msg):
        nonlocal fallos
        if not cond:
            fallos += 1
            print(f"  FALLO {msg}")

    item = buscar_item(filas, "3304340068")
    check(item is not None, "no encuentra el item pasando el id como string")
    check(buscar_item(filas, 3304340068) is not None,
          "no encuentra el item pasando el id como entero")
    check(buscar_item(filas, 999) is None, "inventa un item que no esta")
    check(buscar_item([], 111) is None, "revienta con filas vacias")
    check(buscar_item([{"podio": {}}], 111) is None, "revienta sin clave items")

    tech = campos_tech(item["campos"])
    check([e for e, _ in tech] == ["tech-1-ptl-original-pricing",
                                   "tech-2-ptl-original-pricing"],
          f"filtra mal los campos tech-: {[e for e, _ in tech]}")
    check(campos_tech({}) == [], "revienta con campos vacios")
    check(campos_tech(None) == [], "revienta con campos a None")

    check(es_calculado(dict(tech)["tech-1-ptl-original-pricing"]),
          "no detecta un campo calculation")
    check(not es_calculado(dict(tech)["tech-2-ptl-original-pricing"]),
          "toma un number por calculation")
    check(not es_calculado(None), "revienta con meta a None")

    print(f"autochequeo: 11 comprobaciones, {fallos} fallos")
    return 1 if fallos else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("item_id", nargs="?", help="item_id de Podio, p.ej. 3304340068")
    ap.add_argument("--tipo", help="QID | PTL | PAR")
    ap.add_argument("--anio", type=int, help="año de la app, p.ej. 2026")
    ap.add_argument("--json", metavar="RUTA", help="vuelca el item crudo a un fichero")
    ap.add_argument("--autochequeo", action="store_true",
                    help="prueba la extraccion y sale (ni credenciales ni red)")
    args = ap.parse_args()

    if args.autochequeo:
        return _autochequeo()
    if not (args.item_id and args.tipo and args.anio):
        ap.error("hacen falta item_id, --tipo y --anio (o --autochequeo)")

    print(f"\nAPI: {BASE}    (SOLO LECTURA: login + GET /admin/podio/parity)")
    print("\nCredenciales de un Full Admin (no se guardan ni se imprimen):")
    try:
        correo = input("  correo: ").strip()
        clave = getpass.getpass("  contrasena: ")
    except EOFError:
        # Sin terminal —pipeline, CI, un agente— `input()` reventaba con un
        # traceback que parecia un fallo del script. Es una condicion normal.
        sys.exit("\n\nno hay terminal: este script se ejecuta a mano, porque el "
                 "login pide la contrasena de un Full Admin.\n"
                 "Usa --autochequeo para probarlo sin credenciales ni red.")
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
    print(f"  dentro como {ud.get('Member_Name')} — rol "
          f"{(ud.get('role_detail') or {}).get('Name')}")

    # `parity` no sabe leer un item suelto: hay que enumerar la app-año y buscar
    # dentro. Se reencadena por `siguiente_offset` cuando se agota el
    # presupuesto de reloj de la funcion (Paridad.py:107).
    item, offset, paginas = None, 0, 0
    while item is None:
        ruta = (f"/admin/podio/parity?type={args.tipo}&year={args.anio}"
                f"&enumerar=true&campos=true&offset={offset}")
        print(f"\nEnumerando {args.tipo}/{args.anio} desde offset {offset}...")
        cod, resp = _peticion("GET", ruta, token=token)
        if cod != 200:
            detalle = (resp.get("detail") or resp.get("error") or json.dumps(resp))[:200] \
                if isinstance(resp, dict) else str(resp)[:200]
            sys.exit(f"parity fallo ({cod}): {detalle}")

        paginas += 1
        filas = resp.get("filas") or []
        for e in resp.get("errores") or []:
            print(f"  ERROR de app: {e}")
        item = buscar_item(filas, args.item_id)

        siguiente = next((f.get("siguiente_offset") for f in filas
                          if f.get("siguiente_offset") is not None), None)
        if item is not None or siguiente is None:
            if item is None:
                # Rule 5 del CLAUDE.md: un tramo que acaba sin el item no es
                # "no existe", es "no salio en lo que se miro". Se dice cual.
                mirados = sum((f.get("podio") or {}).get("enumerados") or 0 for f in filas)
                sys.exit(f"\nitem {args.item_id} NO aparece en {args.tipo}/{args.anio} "
                         f"tras {paginas} pagina(s) y {mirados} items enumerados. "
                         "Comprueba el tipo y el año de la app antes de concluir "
                         "que el item no existe.")
            break
        offset = siguiente

    campos = item.get("campos") or {}
    print(f"\nitem {args.item_id}  ({item.get('app_item_id_formatted')})  "
          f"— {len(campos)} campos auditables\n")

    tech = campos_tech(campos)
    if not tech:
        print("  (ninguna casilla tech-* entre los campos auditables)")
    for eid, meta in tech:
        marca = "CALCULADO" if es_calculado(meta) else meta.get("type", "?")
        print(f"  {eid:34} [{marca:11}] {meta.get('label')}")
        print(f"    values: {json.dumps(meta.get('values'), ensure_ascii=False)}")

    calculados = [eid for eid, meta in tech if es_calculado(meta)]
    print("\nVEREDICTO")
    if calculados:
        print("  Casillas CALCULADAS por Podio: " + ", ".join(calculados))
        print("  No se pueden escribir ni a mano ni por API. Lo que se corrige")
        print("  son los POs enlazados, no la casilla.")
    else:
        print("  Ninguna casilla tech-* es de calculo: su valor lo escribio")
        print("  alguien. Es editable desde la UI; averigua quien lo puso antes")
        print("  de pisarlo.")

    if args.json:
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(item, fh, indent=2, ensure_ascii=False)
        print(f"\nitem crudo escrito en {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
