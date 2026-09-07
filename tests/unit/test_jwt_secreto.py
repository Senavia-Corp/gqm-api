"""O-07 · Las claves de firma no dependen del orden de los imports.

`jwt_handler` leía `LOGIN_SECRET_KEY` y `REFRESH_SECRET_KEY` con `os.getenv` en
el momento del IMPORT, y quien mete el `.env` en `os.environ` es
`load_dotenv()` dentro de `src/config.py`. Importar `jwt_handler` primero
congelaba las dos en `None`, y cargar el `.env` después ya no lo arreglaba.

Con la clave a `None`:
  · `jwt.encode` lanza `TypeError: Expected a string value` desde dentro de
    PyJWT — un 500 en `/auth/login` que no menciona ninguna variable.
  · `jwt.decode`, con su `except Exception`, devuelve `None`: TODA petición
    autenticada pasa a 401 sin dejar pista. Esta mitad es la peor.

Así se descubrió: al meter dos ficheros de prueba nuevos en la misma corrida
cambió el orden de imports y 94 tests que no tocaban nada de esto empezaron a
dar ese `TypeError`. La aplicación funcionaba sólo porque `main.py` importa
`src.config` pronto — suerte de orden, no diseño.
"""
import subprocess
import sys

import pytest

RAIZ = "/home/user/gqm-api"


def _en_proceso_limpio(codigo: str):
    """Un intérprete nuevo: es la única forma de probar el orden de imports,
    porque dentro de pytest `src.config` ya está importado desde hace rato."""
    return subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0, {RAIZ!r})\n{codigo}"],
        capture_output=True, text=True, cwd=RAIZ)


def test_la_clave_vale_aunque_jwt_handler_se_importe_primero():
    r = _en_proceso_limpio(
        "import src.utils.middleware.auth.jwt_handler as jh\n"
        "t = jh.create_access_token({'sub': 'prueba'})\n"
        "assert jh.decode_access_token(t)['sub'] == 'prueba'\n"
        "print('OK')\n")
    assert "OK" in r.stdout, (
        "firmar/verificar falló importando jwt_handler antes que src.config:\n"
        + r.stderr[-1500:])


def test_y_tambien_si_src_config_va_primero():
    """El caso que YA funcionaba: no se arregla uno rompiendo el otro."""
    r = _en_proceso_limpio(
        "import src.config\n"
        "import src.utils.middleware.auth.jwt_handler as jh\n"
        "t = jh.create_access_token({'sub': 'prueba'})\n"
        "assert jh.decode_access_token(t)['sub'] == 'prueba'\n"
        "print('OK')\n")
    assert "OK" in r.stdout, r.stderr[-1500:]


def test_una_clave_ausente_dice_QUE_falta():
    """Sin esto, un despliegue sin la variable se manifiesta como «a todo el
    mundo se le ha caducado la sesión» en vez de como un fallo de
    configuración. El mensaje tiene que nombrar la variable."""
    r = _en_proceso_limpio(
        "import os\n"
        "os.environ['LOGIN_SECRET_KEY'] = ''\n"
        "import src.utils.middleware.auth.jwt_handler as jh\n"
        "jh._clave.__globals__['_config'] = None\n"
        "import decouple\n"
        "decouple.config = lambda *a, **k: ''\n"
        "try:\n"
        "    jh.create_access_token({'sub': 'x'})\n"
        "except jh.ClaveJWTAusente as e:\n"
        "    print('MENSAJE:', e)\n"
        "else:\n"
        "    print('NO LANZO NADA')\n")
    assert "MENSAJE:" in r.stdout, f"no lanzó ClaveJWTAusente: {r.stdout} {r.stderr[-800:]}"
    assert "LOGIN_SECRET_KEY" in r.stdout, "el error no dice qué variable falta"


def test_decode_sigue_devolviendo_None_con_un_token_invalido():
    """El contrato que usan los llamadores no cambia: token malo → None, no
    excepción. Sólo la clave ausente sube."""
    from src.utils.middleware.auth.jwt_handler import decode_access_token
    assert decode_access_token("esto-no-es-un-jwt") is None
    assert decode_access_token("") is None
