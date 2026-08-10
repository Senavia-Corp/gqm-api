"""A-9: desarrollo no puede escribir en items de Podio de producción.

Contexto (10-ago-2026): la BD de develop está llena de `podio_item_id` de
PRODUCCIÓN — 97 de 100 clientes y 22 de 57 communities apuntan a la app real
22192695. Y las apps TEST comparten el espacio de Podio 6405055 con las reales,
así que el token de prueba alcanza producción (lectura comprobada, HTTP 200).

Resultado: un `PATCH /clients/<id>?sync_podio=true` desde dev escribía sobre la
ficha REAL del cliente. La guarda de `PodioBaseService` lo corta.

Estos tests no llaman a Podio: se sustituye la resolución del item.
"""
import pytest
import requests

from src.config import APP_ENV, app_ids_configurados
from src.podio.services.podio_base_services import (
    EscrituraFueraDeEntorno,
    PodioBaseService,
)

APP_CLI_PRODUCCION = "22192695"


class _RespuestaFalsa:
    def __init__(self, app_id):
        self._app_id = app_id

    def raise_for_status(self):
        return None

    def json(self):
        return {"app": {"app_id": self._app_id}}


def _servicio():
    ids = sorted(app_ids_configurados())
    return PodioBaseService("CLI", ids[0]), ids


def test_la_lista_blanca_no_incluye_produccion():
    ids = app_ids_configurados()
    assert ids, "debe haber apps configuradas"
    assert APP_CLI_PRODUCCION not in ids, (
        "la app CLI de PRODUCCIÓN no puede estar en la lista blanca de un entorno de test"
    )


@pytest.mark.skipif(APP_ENV != "test", reason="la guarda solo actúa con APP_ENV=test")
def test_update_en_item_de_produccion_se_bloquea(monkeypatch):
    svc, _ = _servicio()
    monkeypatch.setattr(requests, "get", lambda *a, **k: _RespuestaFalsa(APP_CLI_PRODUCCION))

    # Si la guarda falla, esto llegaría al PUT: lo hacemos explotar para que el
    # test no pueda pasar por accidente.
    def _put_prohibido(*a, **k):
        raise AssertionError("¡Se intentó el PUT a Podio! La guarda no cortó.")

    monkeypatch.setattr(requests, "put", _put_prohibido)

    with pytest.raises(EscrituraFueraDeEntorno) as e:
        svc.update_item(2122673808, {"Client_Community": "no debería llegar"})
    assert APP_CLI_PRODUCCION in str(e.value)


@pytest.mark.skipif(APP_ENV != "test", reason="la guarda solo actúa con APP_ENV=test")
def test_delete_en_item_de_produccion_se_bloquea(monkeypatch):
    svc, _ = _servicio()
    monkeypatch.setattr(requests, "get", lambda *a, **k: _RespuestaFalsa(APP_CLI_PRODUCCION))
    monkeypatch.setattr(
        requests, "delete",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("¡Se intentó el DELETE!")))

    with pytest.raises(EscrituraFueraDeEntorno):
        svc.delete_item("2122673808")


@pytest.mark.skipif(APP_ENV != "test", reason="la guarda solo actúa con APP_ENV=test")
def test_item_de_una_app_de_test_si_pasa(monkeypatch):
    svc, ids = _servicio()
    monkeypatch.setattr(requests, "get", lambda *a, **k: _RespuestaFalsa(ids[0]))
    # No debe levantar: la guarda no puede bloquear el trabajo legítimo de dev.
    svc._exigir_app_permitida(123456, "UPDATE")


@pytest.mark.skipif(APP_ENV != "test", reason="la guarda solo actúa con APP_ENV=test")
def test_si_no_se_puede_verificar_el_item_NO_se_escribe(monkeypatch):
    """Fail-closed: perder una sync en dev es barato; escribir en prod no."""
    svc, _ = _servicio()

    def _get_que_falla(*a, **k):
        raise requests.exceptions.ConnectionError("sin red")

    monkeypatch.setattr(requests, "get", _get_que_falla)
    with pytest.raises(EscrituraFueraDeEntorno):
        svc._exigir_app_permitida(999, "UPDATE")
