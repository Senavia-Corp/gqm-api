#!/usr/bin/env python3
"""Compara `jwt_handler` de `main` con el de esta rama en varios entornos.

Sirve para responder UNA pregunta antes de mezclar a producción: *¿hay algún
entorno en el que hoy se pueda iniciar sesión y con el código nuevo no?*

O-07 cambió cuándo y cómo se leen `LOGIN_SECRET_KEY`, `REFRESH_SECRET_KEY` y
las dos duraciones. Razonar sobre eso leyendo el diff no vale: `main` lee las
duraciones con `int(os.getenv(...))` **en el import**, así que algunos fallos
de configuración se manifiestan al arrancar y otros al firmar, y la única
forma honesta de compararlos es ejecutar las dos versiones.

Cada escenario corre en un intérprete nuevo con un entorno construido a mano
(sin heredar el del padre, que trae el `.env` ya cargado). Se distingue entre
fallar **en el import** (la aplicación no levanta) y fallar **al usar** (la
aplicación levanta y el error sale en `/auth/login`), porque el impacto en
producción no es el mismo.

    .venv/bin/python scripts/comparar_jwt_entornos.py
"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RELATIVA = "src/utils/middleware/auth/jwt_handler.py"

# El hijo carga el módulo por ruta —no por nombre— para poder cargar la versión
# de `main` sin tocar el árbol de trabajo.
HIJO = textwrap.dedent("""
    import importlib.util, json, sys
    ruta = sys.argv[1]
    spec = importlib.util.spec_from_file_location("jh_bajo_prueba", ruta)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        print(json.dumps({"fase": "import", "error": type(e).__name__}))
        raise SystemExit(0)
    try:
        mod.create_access_token({"sub": "x"})
        print(json.dumps({"fase": "ok", "error": None}))
    except Exception as e:
        print(json.dumps({"fase": "uso", "error": type(e).__name__}))
""")

CLAVES = {"LOGIN_SECRET_KEY": "s3cr3t", "REFRESH_SECRET_KEY": "r3fr3sh"}

ESCENARIOS = {
    "las dos claves presentes":     {**CLAVES, "ACCESS_TOKEN_EXPIRES_MIN": "60"},
    "sin LOGIN_SECRET_KEY":         {"REFRESH_SECRET_KEY": "r3fr3sh", "ACCESS_TOKEN_EXPIRES_MIN": "60"},
    "ACCESS_TOKEN_EXPIRES_MIN=''":  {**CLAVES, "ACCESS_TOKEN_EXPIRES_MIN": ""},
    "ACCESS_TOKEN_EXPIRES_MIN=abc": {**CLAVES, "ACCESS_TOKEN_EXPIRES_MIN": "abc"},
    "ACCESS_TOKEN_EXPIRES_MIN=0":   {**CLAVES, "ACCESS_TOKEN_EXPIRES_MIN": "0"},
    "duración ausente":             {**CLAVES},
}


def _version_de_main(destino: Path) -> Path:
    """El fichero tal y como está en `origin/main`, sin tocar el árbol."""
    r = subprocess.run(["git", "show", f"origin/main:{RELATIVA}"],
                       cwd=RAIZ, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"no se pudo leer origin/main:{RELATIVA}\n{r.stderr}")
    destino.write_text(r.stdout)
    return destino


def _medir(ruta_modulo: Path, entorno: dict, dir_neutral: str) -> str:
    # El entorno se construye a mano (no se hereda) y el módulo vive en un
    # directorio neutral: ver la nota en `main()` sobre por qué las DOS
    # versiones tienen que estar fuera del repositorio para que esto mida algo.
    env = {"PATH": os.environ["PATH"], "HOME": "/nonexistent", **entorno}
    r = subprocess.run([sys.executable, "-c", HIJO, str(ruta_modulo)],
                       capture_output=True, text=True, env=env, cwd=dir_neutral)
    try:
        d = json.loads(r.stdout.strip())
    except Exception:
        return f"(sin salida) {r.stderr.strip().splitlines()[-1:]}"
    if d["fase"] == "ok":
        return "firma y verifica"
    return f'{"IMPORT" if d["fase"] == "import" else "al usar"}: {d["error"]}'


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        # LAS DOS versiones se copian al directorio neutral. Si la de esta rama
        # se leyera desde su sitio en el repositorio, `decouple` subiría desde
        # `src/utils/middleware/auth/` hasta el `.env` de desarrollo y el
        # escenario «sin LOGIN_SECRET_KEY» daría «firma y verifica»: mediría el
        # `.env` del portátil, no el despliegue, que no lo tiene (está en
        # `.gitignore`, así que nunca viaja a Vercel).
        copia_rama = Path(tmp) / "jwt_handler_rama.py"
        copia_rama.write_text((RAIZ / RELATIVA).read_text())
        versiones = {
            "main": _version_de_main(Path(tmp) / "jwt_handler_main.py"),
            "esta rama": copia_rama,
        }
        ancho = max(len(e) for e in ESCENARIOS) + 2
        print(f"{'escenario':<{ancho}} {'main':<28} {'esta rama':<28} veredicto")
        print("-" * (ancho + 70))
        peores = []
        for nombre, entorno in ESCENARIOS.items():
            a = _medir(versiones["main"], entorno, tmp)
            b = _medir(versiones["esta rama"], entorno, tmp)
            funciona_a, funciona_b = a == "firma y verifica", b == "firma y verifica"
            if funciona_a and not funciona_b:
                veredicto = "REGRESIÓN: la rama rehúsa donde main firma"
                peores.append(nombre)
            elif funciona_b and not funciona_a:
                veredicto = "la rama mejora"
            else:
                veredicto = "igual"
            print(f"{nombre:<{ancho}} {a:<28} {b:<28} {veredicto}")

    print()
    if peores:
        # Sólo se espera uno: una duración <= 0, que en `main` firma tokens ya
        # caducados. Cualquier OTRO renglón aquí sí bloquearía el despliegue.
        print("Renglones donde la rama rehúsa y main no:")
        for n in peores:
            print(f"  · {n}")
        print("\nRevisar uno por uno: sólo es aceptable el de la duración <= 0,")
        print("que en `main` firma sesiones ya caducadas.")
        return 1
    print("Ningún entorno en el que main firme y esta rama no.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
