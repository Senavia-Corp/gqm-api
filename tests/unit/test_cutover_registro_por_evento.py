"""Las tres piezas que hacen posible ROTAR el token sin cambiar la topologia.

Contexto: los 48 hooks de produccion se registraron sin token, los creo una
cuenta de USUARIO (medido el 1-sep-2026) y hay que rotarlos. Tres cosas del
codigo lo impedian, y cada test fija una:

  1. `register` creaba SIEMPRE los 4 eventos, porque FILE_CHANGE_APP_TYPES
     contiene las 7 familias. Las apps reales no estan asi: PMC, QID/2024,
     PTL/2024 y PAR/2024 tienen 3. Re-registrar sin acotar les añadiria un
     `file.change` que hoy no tienen, y empezaria a subir adjuntos de años
     cerrados a Cloudinary.
  2. El token se concatena a la RUTA sin escapar. Con un `/` la URL lleva un
     segmento de mas, Flask NO enruta, y mueren las entregas *y* el hook.verify:
     el hook queda `inactive` para siempre y /register responde 200 igual.
  3. `/clear` decide "propio" por PREFIJO de PUBLIC_URL, y los hooks NUEVOS
     comparten ese prefijo. Sin guarda borraria las dos generaciones. Y como los
     viejos los creo un usuario (403 al app token) y los nuevos los crea la app,
     borraria EXACTAMENTE los que hay que conservar.
"""
import pytest

from src.podio.webhook import func_hooks
from src.podio.webhook.func_hooks import (
    clear_existing_webhooks,
    build_webhook_target,
    register_podio_webhooks,
    token_de_webhook,
)

HEX64 = "a1b2c3d4" * 8          # 64 caracteres, valido
VAR = "PODIO_WEBHOOK_TOKEN"


@pytest.fixture(autouse=True)
def _sin_esperas(monkeypatch):
    """@retry_api atrapa Exception y duerme 2 s y 4 s. En un test de validacion
    eso son 6 s de reloj por nada."""
    monkeypatch.setattr("src.utils.middleware.retries.retries.time.sleep",
                        lambda *_: None)


# ── 1. Registro por evento ──────────────────────────────────────────────────

class _RespuestaFalsa:
    status_code = 200

    def json(self):
        return {"hook_id": 1}


@pytest.fixture
def _podio_falso(monkeypatch):
    """Captura los eventos que se habrian registrado, sin hablar con Podio."""
    registrados = []
    monkeypatch.setattr(func_hooks, "get_podio_headers", lambda *a, **k: {})
    monkeypatch.setattr(func_hooks, "get_app_id", lambda *a, **k: 12345)

    def _post(url, headers=None, json=None, **kw):
        registrados.append(json["type"])
        return _RespuestaFalsa()

    monkeypatch.setattr(func_hooks.requests, "post", _post)
    return registrados


def test_sin_events_registra_los_cuatro(_podio_falso):
    """El comportamiento de siempre no cambia: quien no pida nada, recibe 4."""
    register_podio_webhooks("QID", year=2026)
    assert _podio_falso == ["item.create", "item.update", "item.delete", "file.change"]


def test_con_events_registra_EXACTAMENTE_esos(_podio_falso):
    """Es lo que permite rotar PMC y las tres de 2024 conservando sus 3 hooks."""
    register_podio_webhooks("QID", year=2024,
                            events=["item.create", "item.update", "item.delete"])
    assert _podio_falso == ["item.create", "item.update", "item.delete"]
    assert "file.change" not in _podio_falso


def test_events_duplicados_no_duplican_peticiones(_podio_falso):
    register_podio_webhooks("PMC", events=["item.update", "item.update"])
    assert _podio_falso == ["item.update"]


def test_evento_desconocido_se_rechaza(_podio_falso):
    with pytest.raises(ValueError, match="no reconocidos"):
        register_podio_webhooks("PMC", events=["item.update", "item.explode"])
    assert _podio_falso == [], "no debe registrar nada si la lista es invalida"


def test_lista_vacia_se_rechaza(_podio_falso):
    with pytest.raises(ValueError, match="vacia"):
        register_podio_webhooks("PMC", events=[])


# ── 2. Forma del token ──────────────────────────────────────────────────────

@pytest.mark.parametrize("malo", [
    "abc/def" + "0" * 32,        # la barra mete un segmento: Flask no enruta
    "abc%2f" + "0" * 32,         # secuencia de escape
    "ABCDEF" + "0" * 32,         # mayusculas: no es la forma que emitimos
    "deadbeef",                  # 8 caracteres: demasiado corto
    "a" * 31,                    # 31: justo por debajo del minimo
    "z" * 64,                    # no hexadecimal
    "  " + "a" * 64,             # espacio delante
    "a" * 64 + " ",              # y detras, que es el caso invisible
])
def test_token_mal_formado_se_rechaza(monkeypatch, malo):
    monkeypatch.setenv(VAR, malo)
    with pytest.raises(ValueError, match="mal formado"):
        token_de_webhook()


def test_token_hexadecimal_se_acepta(monkeypatch):
    monkeypatch.setenv(VAR, HEX64)
    assert token_de_webhook() == HEX64


def test_sin_token_no_lanza(monkeypatch):
    """El estado de hoy en produccion: la variable no existe y no pasa nada."""
    monkeypatch.setenv(VAR, "")
    assert token_de_webhook() == ""


def test_el_token_malo_NO_llega_a_grabarse_en_una_url(monkeypatch):
    """La barrera de verdad: un token ilegal grabado en 48 URLs queda congelado
    ahi, y el sintoma es 404 en todo — incluido el hook.verify — sin un solo
    error visible."""
    monkeypatch.setenv(VAR, "malo/" + "a" * 40)
    with pytest.raises(ValueError):
        build_webhook_target("QID", 2026)


def test_el_mensaje_de_error_no_filtra_el_token(monkeypatch):
    """El valor es un secreto y este mensaje acaba en logs."""
    secreto = "z" * 50
    monkeypatch.setenv(VAR, secreto)
    with pytest.raises(ValueError) as e:
        token_de_webhook()
    assert secreto not in str(e.value)


# ── 3. La guarda de /clear ──────────────────────────────────────────────────

def _hook(hid, url):
    return {"hook_id": hid, "url": url}


@pytest.fixture
def _clear_falso(monkeypatch):
    borrados = []
    monkeypatch.setattr(func_hooks, "get_podio_headers", lambda *a, **k: {})

    class _R:
        status_code = 200
    monkeypatch.setattr(func_hooks.requests, "delete",
                        lambda url, headers=None, **kw: (
                            borrados.append(int(url.rsplit("/", 1)[1])), _R())[1])
    return borrados


def test_clear_conserva_los_hooks_del_token_vigente(monkeypatch, _clear_falso):
    """El fallo que esto impide: /clear deja la app con CERO hooks y responde
    `success: true`, porque el endpoint no mira nada del cuerpo."""
    monkeypatch.setenv(VAR, HEX64)
    base = func_hooks.PUBLIC_URL.rstrip("/") + "/webhook/podio/jobs/QID/2026"
    monkeypatch.setattr(func_hooks, "list_webhooks", lambda *a, **k: [
        _hook(111, base),                    # viejo, sin token
        _hook(222, f"{base}/{HEX64}"),       # nuevo, con el token vigente
    ])

    ok, detalle = clear_existing_webhooks("QID", year=2026)

    assert ok
    assert _clear_falso == [111], "solo debe borrarse la generacion legado"
    assert detalle["conservados_por_token"] == 1


def test_sin_token_definido_clear_se_comporta_como_siempre(monkeypatch, _clear_falso):
    """Sin token no hay generacion que proteger: la guarda no debe cambiar nada."""
    monkeypatch.setenv(VAR, "")
    base = func_hooks.PUBLIC_URL.rstrip("/") + "/webhook/podio/jobs/QID/2026"
    monkeypatch.setattr(func_hooks, "list_webhooks", lambda *a, **k: [
        _hook(111, base), _hook(222, base + "/otro"),
    ])

    ok, detalle = clear_existing_webhooks("QID", year=2026)

    assert ok
    assert sorted(_clear_falso) == [111, 222]
    assert detalle["conservados_por_token"] == 0


def test_clear_sigue_sin_tocar_los_hooks_ajenos(monkeypatch, _clear_falso):
    """REG-010 sigue vigente: la guarda nueva no puede haberlo aflojado."""
    monkeypatch.setenv(VAR, HEX64)
    monkeypatch.setattr(func_hooks, "list_webhooks", lambda *a, **k: [
        _hook(333, "https://api.taskipos.com/webhook/podio/jobs/QID/2026"),
    ])

    ok, detalle = clear_existing_webhooks("QID", year=2026)

    assert ok
    assert _clear_falso == []
    assert detalle["omitidos_ajenos"] == 1


# ── 4. Borrado explicito por hook_id: el camino de vuelta ───────────────────

def _delete_que_devuelve(monkeypatch, codigo, texto=""):
    llamadas = []

    class _R:
        status_code = codigo
        text = texto

    def _delete(url, headers=None, **kw):
        llamadas.append(url)
        return _R()

    monkeypatch.setattr(func_hooks, "get_podio_headers", lambda *a, **k: {})
    monkeypatch.setattr(func_hooks.requests, "delete", _delete)
    return llamadas


@pytest.mark.parametrize("codigo", [200, 202, 204])
def test_borrar_hook_exito(monkeypatch, codigo):
    llamadas = _delete_que_devuelve(monkeypatch, codigo)
    ok, detalle = func_hooks.borrar_hook(999, "QID", year=2026)
    assert ok and detalle["hook_id"] == 999
    assert llamadas == ["https://api.podio.com/hook/999"]


def test_borrar_hook_404_cuenta_como_exito(monkeypatch):
    """El estado final es el mismo —no existe—, y el rollback debe poder
    reintentarse sin quedarse atascado en uno que ya se borro."""
    _delete_que_devuelve(monkeypatch, 404)
    ok, detalle = func_hooks.borrar_hook(999, "QID", year=2026)
    assert ok and detalle["status"] == 404


def test_borrar_hook_403_es_fallo(monkeypatch):
    """Es el caso esperado con los 48 VIEJOS: los creo una cuenta de usuario,
    asi que el app token no puede borrarlos. Tiene que decirlo, no tragarselo."""
    _delete_que_devuelve(monkeypatch, 403, "forbidden")
    ok, detalle = func_hooks.borrar_hook(24303236, "CLI")
    assert not ok and detalle["status"] == 403
