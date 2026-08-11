"""El paginador de Podio tiene que devolver los contadores, y reintentar poco.

`get_items` hacía `.get("items", [])` y tiraba `filtered`/`total`. Sin ellos no
hay forma de saber cuándo se terminó de paginar una app ni de comparar su
contador contra la BD, que es justo lo que el cliente mira para firmar.

El segundo tema es el reloj: el importador corre con presupuesto de segundos y
`retry_api` duerme 2 s y luego 4 s ante *cualquier* excepción. Un 403 costaba
6 s por página que nunca iba a funcionar.

Sin red: se sustituyen `_headers` y `requests.post`.
"""
import pytest
import requests

from src.podio.services.podio_base_services import PodioBaseService
from src.utils.middleware.retries import retries


class _Respuesta:
    """Respuesta de Podio de mentira. `estado` != 200 levanta HTTPError."""

    def __init__(self, cuerpo=None, estado=200, retry_after=None):
        self._cuerpo = cuerpo or {}
        self.status_code = estado
        self.headers = {} if retry_after is None else {"Retry-After": retry_after}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f"{self.status_code} de mentira", response=self)

    def json(self):
        return self._cuerpo


@pytest.fixture
def servicio(monkeypatch):
    svc = PodioBaseService("QID", "999", year=2026)
    monkeypatch.setattr(svc, "_headers", lambda: {"Authorization": "OAuth2 falso"})
    return svc


@pytest.fixture
def sin_dormir(monkeypatch):
    """El reintento no puede robar segundos reales a la suite."""
    dormido = []
    monkeypatch.setattr(retries.time, "sleep", lambda s: dormido.append(s))
    return dormido


def _contador_post(monkeypatch, respuestas):
    """Sustituye requests.post; devuelve la lista de llamadas registradas."""
    llamadas = []
    cola = list(respuestas)

    def _post(url, **kwargs):
        llamadas.append((url, kwargs.get("json")))
        return cola.pop(0) if len(cola) > 1 else cola[0]

    monkeypatch.setattr(requests, "post", _post)
    return llamadas


def test_get_items_page_conserva_filtered_y_total(servicio, monkeypatch):
    _contador_post(monkeypatch, [
        _Respuesta({"items": [{"item_id": 1}], "filtered": 80, "total": 80})])

    pagina = servicio.get_items_page(limit=1, offset=0)

    assert pagina["filtered"] == 80
    assert pagina["total"] == 80
    assert pagina["items"] == [{"item_id": 1}]
    assert (pagina["limit"], pagina["offset"]) == (1, 0)


def test_get_items_sigue_devolviendo_solo_la_lista(servicio, monkeypatch):
    """Regresión de firma: hay llamadores vivos que esperan una lista pelada."""
    _contador_post(monkeypatch, [
        _Respuesta({"items": [{"item_id": 7}], "filtered": 1, "total": 1})])

    assert servicio.get_items(limit=50, offset=0) == [{"item_id": 7}]


def test_offset_y_limit_llegan_a_podio(servicio, monkeypatch):
    llamadas = _contador_post(monkeypatch, [
        _Respuesta({"items": [], "filtered": 500, "total": 500})])

    servicio.get_items_page(limit=500, offset=1000)

    url, cuerpo = llamadas[0]
    assert url.endswith("/item/app/999/filter/")
    assert cuerpo == {"limit": 500, "offset": 1000}


def test_un_403_no_se_reintenta(servicio, monkeypatch, sin_dormir):
    """El que de verdad falla si alguien reusa el retry_api global.

    Un token malo no se arregla esperando: reintentarlo son 6 s del presupuesto
    de reloj tirados por cada página.
    """
    llamadas = _contador_post(monkeypatch, [_Respuesta(estado=403)])

    with pytest.raises(requests.exceptions.HTTPError):
        servicio.get_items_page()

    assert len(llamadas) == 1
    assert sin_dormir == []


def test_un_503_si_se_reintenta(servicio, monkeypatch, sin_dormir):
    llamadas = _contador_post(monkeypatch, [_Respuesta(estado=503)])

    with pytest.raises(requests.exceptions.HTTPError):
        servicio.get_items_page()

    assert len(llamadas) == 3
    assert sin_dormir == [0.5, 1.0]


def test_un_429_respeta_retry_after(servicio, monkeypatch, sin_dormir):
    _contador_post(monkeypatch, [
        _Respuesta(estado=429, retry_after="7"),
        _Respuesta({"items": [], "filtered": 0, "total": 0})])

    servicio.get_items_page()

    assert sin_dormir == [7.0]


def test_una_caida_de_red_se_reintenta(servicio, monkeypatch, sin_dormir):
    llamadas = []

    def _post(url, **kwargs):
        llamadas.append(url)
        raise requests.exceptions.ConnectionError("sin red")

    monkeypatch.setattr(requests, "post", _post)

    with pytest.raises(requests.exceptions.ConnectionError):
        servicio.get_items_page()

    assert len(llamadas) == 3
