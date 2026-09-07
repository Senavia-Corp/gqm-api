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
import os
import subprocess
import sys

import pytest

RAIZ = "/home/user/gqm-api"


# Las variables que `load_dotenv()` mete en el entorno del PADRE y que el hijo
# no debe heredar: si las ve, el `os.getenv` en el import del codigo ANTIGUO
# tambien las encuentra y la prueba pasa contra el codigo roto.
_VARIABLES_A_OCULTAR = ("LOGIN_SECRET_KEY", "REFRESH_SECRET_KEY")


def _entorno_sin_secretos():
    return {k: v for k, v in os.environ.items() if k not in _VARIABLES_A_OCULTAR}


def _en_proceso_limpio(codigo: str, *, con_secretos_del_padre: bool = False):
    """Un intérprete nuevo Y con el entorno saneado.

    Un intérprete nuevo es la única forma de probar el orden de imports, porque
    dentro de pytest `src.config` ya está importado desde hace rato. Pero con
    eso solo no basta:

    `subprocess.run` SIN `env=` hereda el entorno del padre, y
    `verificar_portal.sh` corre `test_rbac_matrix.py` ANTES que este fichero en
    el MISMO proceso pytest. Ese fichero importa `main` → `src.config` →
    `load_dotenv()`, que mete `LOGIN_SECRET_KEY` en `os.environ` del padre. El
    hijo la heredaba, el `os.getenv` en el import la encontraba, y **el código
    antiguo también funcionaba**: esta prueba pasaba VERDE contra el fallo que
    existe para cazar. Medida en aislado daba `2 failed`; en el orden del arnés,
    `1 failed, 35 passed`.

    Por eso el hijo recibe un entorno del que se han quitado las dos claves. Lo
    afirma `test_el_hijo_no_hereda_las_claves_del_padre`, que es la prueba que
    guarda a esta prueba.
    """
    entorno = os.environ.copy() if con_secretos_del_padre else _entorno_sin_secretos()
    return subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0, {RAIZ!r})\n{codigo}"],
        capture_output=True, text=True, cwd=RAIZ, env=entorno)


def test_el_hijo_no_hereda_las_claves_del_padre():
    """La prueba que guarda a las demás.

    Si esto se rompe, `test_la_clave_vale_aunque_jwt_handler_se_importe_primero`
    deja de poder fallar y nadie se entera: el arnés seguiría en verde con la
    regresión de O-07 dentro.
    """
    r = _en_proceso_limpio(
        "import os\n"
        "print('LOGIN=', repr(os.environ.get('LOGIN_SECRET_KEY')))\n"
        "print('REFRESH=', repr(os.environ.get('REFRESH_SECRET_KEY')))\n")
    assert "LOGIN= None" in r.stdout, f"el hijo VE la clave del padre: {r.stdout}"
    assert "REFRESH= None" in r.stdout, f"el hijo VE la clave del padre: {r.stdout}"


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
        # `_clave` importa decouple DENTRO de la función, así que hay que
        # sustituirlo en el módulo `decouple`, no en los globales de `_clave`:
        # tocar ahí no hacía absolutamente nada.
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


# ── La duración de la sesión, cuando la variable existe pero no vale ────────
#
# El arreglo de O-07 introdujo, sin querer, otro fallo silencioso: la primera
# versión de `_entero_de_entorno` se tragaba `'abc'`, `'60m'` y `'5.5'` y
# devolvía 60 minutos como si nada, cuando el código anterior
# (`int(os.getenv(...))`) reventaba al arrancar. Es decir: arreglando un fallo
# de configuración silencioso se metió otro — justo la lección que O-07 venía a
# dejar escrita. Y `'-5'` o `'0'` firmaban tokens ya caducados: todo el mundo
# dentro con la sesión muerta al instante y sin ninguna pista.

MALFORMADOS = ["abc", "60m", "5.5", "", " ", "1e3"]
NO_POSITIVOS = ["0", "-5", "-1"]


@pytest.mark.parametrize("valor", MALFORMADOS)
def test_una_duracion_malformada_no_cae_al_defecto_en_silencio(valor):
    r = _en_proceso_limpio(
        "import os\n"
        f"os.environ['ACCESS_TOKEN_EXPIRES_MIN'] = {valor!r}\n"
        "os.environ['LOGIN_SECRET_KEY'] = 'x' * 32\n"
        "import src.utils.middleware.auth.jwt_handler as jh\n"
        "try:\n"
        "    jh.create_access_token({'sub': 'x'})\n"
        "except jh.ConfiguracionJWTInvalida as e:\n"
        "    print('AVISA:', e)\n"
        "except Exception as e:\n"
        "    print('OTRA:', type(e).__name__, e)\n"
        "else:\n"
        "    print('SILENCIO')\n")
    # La cadena vacía y el espacio SÍ son «ausente»: ahí el defecto es correcto.
    if valor.strip() == "":
        assert "SILENCIO" in r.stdout, r.stdout
        return
    assert "AVISA:" in r.stdout, f"se tragó ACCESS_TOKEN_EXPIRES_MIN={valor!r}: {r.stdout}"
    assert "ACCESS_TOKEN_EXPIRES_MIN" in r.stdout, "el aviso no nombra la variable"


@pytest.mark.parametrize("valor", NO_POSITIVOS)
def test_una_duracion_no_positiva_no_firma_tokens_ya_caducados(valor):
    r = _en_proceso_limpio(
        "import os\n"
        f"os.environ['ACCESS_TOKEN_EXPIRES_MIN'] = {valor!r}\n"
        "os.environ['LOGIN_SECRET_KEY'] = 'x' * 32\n"
        "import src.utils.middleware.auth.jwt_handler as jh\n"
        "try:\n"
        "    t = jh.create_access_token({'sub': 'x'})\n"
        "except jh.ConfiguracionJWTInvalida as e:\n"
        "    print('AVISA:', e)\n"
        "else:\n"
        "    print('FIRMO UN TOKEN CADUCADO:', jh.decode_access_token(t))\n")
    assert "AVISA:" in r.stdout, f"ACCESS_TOKEN_EXPIRES_MIN={valor!r} pasó: {r.stdout}"


def test_una_duracion_ausente_si_usa_el_defecto():
    """El control: si esto se pusiera rojo, la validación estaría rechazándolo
    TODO y las dos pruebas de arriba seguirían verdes por el motivo equivocado."""
    r = _en_proceso_limpio(
        "import os\n"
        "os.environ.pop('ACCESS_TOKEN_EXPIRES_MIN', None)\n"
        "os.environ['LOGIN_SECRET_KEY'] = 'x' * 32\n"
        "import src.utils.middleware.auth.jwt_handler as jh\n"
        "d = jh.decode_access_token(jh.create_access_token({'sub': 'x'}))\n"
        "print('MINUTOS:', round((d['exp'] - d['iat']) / 60))\n")
    assert "MINUTOS: 60" in r.stdout, r.stdout


def test_una_duracion_valida_se_respeta():
    r = _en_proceso_limpio(
        "import os\n"
        "os.environ['ACCESS_TOKEN_EXPIRES_MIN'] = '45'\n"
        "os.environ['LOGIN_SECRET_KEY'] = 'x' * 32\n"
        "import src.utils.middleware.auth.jwt_handler as jh\n"
        "d = jh.decode_access_token(jh.create_access_token({'sub': 'x'}))\n"
        "print('MINUTOS:', round((d['exp'] - d['iat']) / 60))\n")
    assert "MINUTOS: 45" in r.stdout, r.stdout
