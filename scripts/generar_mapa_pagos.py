"""Genera el mapa de huecos de cuotas a técnico desde el esquema real de Podio.

## Por qué se genera y no se teclea

Los slugs son irregulares hasta lo absurdo, y verificarlos a mano es una fuente
garantizada de errores. Medido sobre los 12 volcados de producción:

- El técnico 1 de QID usa `check-amount-payment-1/2/3` para las tres primeras
  cuotas y luego `tech-1-payment-4` … `tech-1-payment-11`.
- El técnico 2 usa `check-amount-payment-N-2`.
- Del 3 en adelante, `tech-N-payment-M`… salvo el técnico 6, cuyas cuotas 2 y 3
  son **`money-4`** y **`money-5`**, y los técnicos 7-9, que usan
  `money-6` … `money-11`.
- Los campos de número de cheque van `check-numbers`, `-2`…`-7`,
  **`check-numberss`** (sic), `check-numbers-9` para el técnico 10, y
  **`ach-numbers`** para el 13.
- El número de cuotas cambia por técnico Y por año: QID 2023 tiene 17 secciones
  de técnico y 2024-2026 tienen 13.

## Las cuatro trampas que resuelve

1. **No todo `money` de la sección es cuota.** `Tech N - H.D. / Materials` vive
   dentro de `TECHNICIAN N PAYMENT SCHEDULE` en PTL y no es un cheque.
2. **No todo `text` es el número de cheque.** `RES/IND` cae dentro de una
   sección de técnico en PAR.
3. **`calculation` NUNCA se emite.** `Tech n Adj Formula`,
   `Total (Left to) Pay` y `Tech n Final Formula` los calcula Podio. Al no
   estar en el artefacto, es imposible escribirlos por accidente.
4. **Colisión real de etiquetas.** QID 2023 tiene dos `money` con la etiqueta
   `Tech 15 - Payment 1` (`tech-15-payment-1-2` y `tech-15-payment-1`). Se
   desempata por `delta` —que es el orden real de la app— y se deja constancia
   en `avisos`.

## Uso

    python scripts/generar_mapa_pagos.py --verificar   # ¿el artefacto está al día?
    python scripts/generar_mapa_pagos.py --escribir    # regenera el artefacto
    python scripts/generar_mapa_pagos.py --fixture     # recorta el fixture de tests
"""
import argparse
import json
import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
ESQUEMA = pathlib.Path.home() / "outputs/gqm-auditoria-campos/esquema"
ARTEFACTO = RAIZ / "src/utils/mappers/from_podio/payment_slots.json"
FIXTURE = RAIZ / "tests/fixtures/esquema_pagos.json"

SECCION = re.compile(r"^TECHNICIAN\s+(\d+)\s+PAYMENT\s+SCHEDULE", re.I)
CUOTA = re.compile(r"^Tech\s+(\d+)\s*-\s*Payment\s+(\d+)\s*$", re.I)
CHEQUE = {"check number(s)", "check numbers(s)", "ach number(s)"}

# PTL no usa pagos parciales — decisión de cliente ya cerrada. Se expresa como
# DATO en el artefacto, no como un `if` perdido en el código.
HABILITADO = {"QID": True, "PAR": True, "PTL": False}

ESQUEMA_VERSION = 1


def cargar_volcados(directorio: pathlib.Path) -> list[dict]:
    salida = []
    for f in sorted(directorio.glob("*-prod.json")):
        d = json.loads(f.read_text())
        if "campos" in d and d.get("job_type"):
            d["_fichero"] = f.name
            salida.append(d)
    return salida


def extraer_pagos(volcado: dict) -> tuple[dict, list[dict]]:
    """`{tech: {"cuotas": {n: ext_id}, "check_numbers": ext_id|None}}` + avisos."""
    techs: dict[int, dict] = {}
    avisos: list[dict] = []

    # `delta` es la posición real del campo en la app: el desempate fiable.
    campos = sorted(volcado["campos"], key=lambda c: c.get("delta") or 0)

    for c in campos:
        if c.get("es_encabezado"):
            continue
        m = SECCION.match(c.get("seccion") or "")
        if not m:
            continue

        tech = int(m.group(1))
        entrada = techs.setdefault(tech, {"cuotas": {}, "check_numbers": None})
        etiqueta = (c.get("label") or "").strip()
        ext = c.get("external_id")

        if c["type"] == "money":
            mc = CUOTA.match(etiqueta)
            if not mc:
                continue                        # `Tech N - H.D. / Materials`
            if int(mc.group(1)) != tech:
                avisos.append({"app": volcado["job_type"], "anio": volcado["anio"],
                               "tech": tech, "campo": ext,
                               "motivo": f"la etiqueta dice tech {mc.group(1)} y la sección tech {tech}",
                               "resolucion": "manda la sección"})
            cuota = int(mc.group(2))
            if cuota in entrada["cuotas"]:
                libre = max(entrada["cuotas"]) + 1
                avisos.append({"app": volcado["job_type"], "anio": volcado["anio"],
                               "tech": tech,
                               "motivo": f"etiqueta duplicada {etiqueta!r}",
                               "campos": [entrada["cuotas"][cuota], ext],
                               "resolucion": f"el segundo por `delta` se renumera a la cuota {libre}"})
                cuota = libre
            entrada["cuotas"][cuota] = ext

        elif c["type"] == "text" and etiqueta.lower() in CHEQUE:
            if entrada["check_numbers"] is None:
                entrada["check_numbers"] = ext

        # `calculation` se ignora a propósito: lo calcula Podio.

    return techs, avisos


def construir_artefacto(directorio: pathlib.Path) -> dict:
    volcados = cargar_volcados(directorio)
    apps: dict[str, dict] = {}
    avisos: list[dict] = []
    fuentes = []

    for v in volcados:
        tipo, anio = v["job_type"], str(v["anio"])
        techs, avs = extraer_pagos(v)
        avisos.extend(avs)
        fuentes.append(v["_fichero"])

        app = apps.setdefault(tipo, {"habilitado": HABILITADO.get(tipo, False), "anios": {}})
        app["anios"][anio] = {
            "app_id": str(v["app_id"]),
            "techs": {str(t): {"cuotas": {str(k): e for k, e in sorted(d["cuotas"].items())},
                               "check_numbers": d["check_numbers"]}
                      for t, d in sorted(techs.items()) if d["cuotas"]},
        }

    return {
        "_comentario": "GENERADO por scripts/generar_mapa_pagos.py — no editar a mano.",
        "esquema_version": ESQUEMA_VERSION,
        "generado_desde": sorted(fuentes),
        "apps": apps,
        "avisos": avisos,
    }


def construir_fixture(directorio: pathlib.Path) -> dict:
    """Los volcados viven fuera del repo; el fixture es el recorte que permite
    que la prueba de regeneración corra en cualquier sitio."""
    recorte = []
    for v in cargar_volcados(directorio):
        campos = [c for c in v["campos"]
                  if SECCION.match(c.get("seccion") or "") and not c.get("es_encabezado")]
        recorte.append({"_fichero": v["_fichero"], "job_type": v["job_type"],
                        "anio": v["anio"], "app_id": v["app_id"], "campos": campos})
    return {"esquema_version": ESQUEMA_VERSION, "volcados": recorte}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--escribir", action="store_true")
    ap.add_argument("--fixture", action="store_true")
    ap.add_argument("--verificar", action="store_true")
    ap.add_argument("--dir", type=pathlib.Path, default=ESQUEMA)
    args = ap.parse_args(argv)

    if not args.dir.exists():
        print(f"⛔ no encuentro los volcados en {args.dir}")
        return 2

    art = construir_artefacto(args.dir)

    if args.fixture:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(construir_fixture(args.dir), indent=1) + "\n")
        print(f"✓ fixture escrito: {FIXTURE}")

    if args.escribir:
        ARTEFACTO.parent.mkdir(parents=True, exist_ok=True)
        ARTEFACTO.write_text(json.dumps(art, indent=2, ensure_ascii=False) + "\n")
        print(f"✓ artefacto escrito: {ARTEFACTO}")

    for tipo, app in sorted(art["apps"].items()):
        marca = "sí" if app["habilitado"] else "NO (decisión de cliente)"
        print(f"\n{tipo} · pagos habilitados: {marca}")
        for anio, d in sorted(app["anios"].items()):
            cuotas = {t: len(v["cuotas"]) for t, v in d["techs"].items()}
            print(f"   {anio}: {len(d['techs'])} técnicos · cuotas por técnico "
                  f"{[cuotas[k] for k in sorted(cuotas, key=int)]}")
    if art["avisos"]:
        print(f"\n{len(art['avisos'])} avisos:")
        for a in art["avisos"]:
            print(f"   {a['app']} {a['anio']} tech {a['tech']}: {a['motivo']} → {a['resolucion']}")

    if args.verificar:
        if not ARTEFACTO.exists():
            print("⛔ el artefacto no existe; corre --escribir")
            return 1
        actual = json.loads(ARTEFACTO.read_text())
        if actual != art:
            print("⛔ el artefacto NO coincide con el esquema. Corre --escribir.")
            return 1
        print("\n✓ el artefacto coincide con el esquema de Podio")

    if not (args.escribir or args.verificar or args.fixture):
        print("\n(informe solamente; usa --escribir para persistirlo)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
