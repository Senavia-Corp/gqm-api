"""Ninguna escritura puede salir hacia Podio sin pasar por el portal.

Tres agujeros que estos tests cierran:

1. `create_item` NO llamaba a ninguna guarda. La lista blanca de A-9 solo cubría
   update y delete, así que el camino que crea items estaba abierto.
2. No había forma de pausar las escrituras salientes durante la ventana de
   reconciliación: `PODIO_READONLY`.
3. La lista blanca deja pasar cualquier app configurada, así que un update
   resuelto con el año equivocado escribía en la app de otro año sin ruido.

Y una invariante que va en la dirección contraria y es igual de importante:
`PODIO_READONLY` **no puede** matar las escrituras ENTRANTES. Si lo hiciera, el
sync de Podio moriría durante la ventana y la divergencia crecería justo
mientras se está arreglando.

Sin red: se sustituyen `_headers` y los verbos de `requests`.
"""
import pytest
import requests

from src.config import APP_ENV, app_ids_configurados
from src.podio.services import podio_base_services as pbs
from src.podio.services.podio_base_services import (
    EscrituraFueraDeEntorno,
    EscrituraPodioBloqueada,
    PodioBaseService,
    PodioReadOnlyService,
)

APP_AJENA = "22192695"  # la app CLI de PRODUCCIÓN


class _Basic:
    """Respuesta de GET /item/<id>/basic."""

    def __init__(self, app_id):
        self._app_id = app_id

    def raise_for_status(self):
        return None

    def json(self):
        return {"app": {"app_id": self._app_id}}


@pytest.fixture
def prohibir_escrituras(monkeypatch):
    """Cualquier POST/PUT/DELETE hacia Podio revienta el test.

    Es la red que hace que estos tests no puedan pasar por accidente: si una
    guarda deja de cortar, el fallo es un AssertionError con la URL, no un
    silencio.
    """
    salidas = []

    def _explota(verbo):
        def _f(url, *a, **k):
            salidas.append((verbo, url))
            raise AssertionError(f"¡{verbo} a Podio! La guarda no cortó: {url}")
        return _f

    for verbo in ("post", "put", "delete"):
        monkeypatch.setattr(requests, verbo, _explota(verbo.upper()))
    return salidas


@pytest.fixture
def servicio(monkeypatch):
    ids = sorted(app_ids_configurados())
    assert ids, "el entorno tiene que tener apps configuradas"
    svc = PodioBaseService("QID", ids[0], year=2026)
    monkeypatch.setattr(svc, "_headers", lambda: {"Authorization": "OAuth2 falso"})
    return svc


def _con_readonly(monkeypatch, valor=True):
    monkeypatch.setattr(pbs, "PODIO_READONLY", valor)


# ---------------------------------------------------------------- PODIO_READONLY

@pytest.mark.parametrize("operacion", ["create", "update", "delete"])
def test_readonly_corta_las_tres_sin_tocar_la_red(
        servicio, monkeypatch, prohibir_escrituras, operacion):
    _con_readonly(monkeypatch)
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Basic(servicio.app_id))

    with pytest.raises(EscrituraPodioBloqueada):
        if operacion == "create":
            servicio.create_item({"x": 1})
        elif operacion == "update":
            servicio.update_item(123, {"x": 1})
        else:
            servicio.delete_item("123")

    assert prohibir_escrituras == [], "no debe salir ni una petición de escritura"


def test_readonly_es_subclase_de_la_excepcion_vieja():
    """Los `except EscrituraFueraDeEntorno` que ya existen la siguen atrapando."""
    assert issubclass(EscrituraPodioBloqueada, EscrituraFueraDeEntorno)


# ---------------------------------------------------------------- create_item

def test_create_en_app_ajena_se_bloquea(monkeypatch, prohibir_escrituras):
    """Hoy fallaba: create_item no llamaba a ninguna guarda."""
    svc = PodioBaseService("CLI", APP_AJENA)
    monkeypatch.setattr(svc, "_headers", lambda: {"Authorization": "OAuth2 falso"})

    with pytest.raises(EscrituraFueraDeEntorno) as e:
        svc.create_item({"Client_Community": "no debería llegar"})

    assert APP_AJENA in str(e.value)
    assert prohibir_escrituras == []


def test_create_en_app_configurada_si_llega_a_la_red(servicio, monkeypatch):
    """La guarda no puede bloquear el trabajo legítimo."""
    llamadas = []

    def _post(url, *a, **k):
        llamadas.append(url)
        raise RuntimeError("corta aquí: solo queríamos ver que la guarda dejó pasar")

    monkeypatch.setattr(requests, "post", _post)

    with pytest.raises(RuntimeError):
        servicio.create_item({"x": 1})

    assert llamadas, "la guarda bloqueó una escritura legítima"


# ---------------------------------------------------------------- match de app

@pytest.mark.skipif(APP_ENV != "test", reason="el match estricto exige la bandera")
def test_update_a_la_app_del_año_equivocado_se_bloquea(
        servicio, monkeypatch, prohibir_escrituras):
    """El item existe y su app está en la lista blanca, pero NO es la del servicio.

    Es el caso que la lista blanca sola no atrapa: `resolve_job_app_year` da el
    año equivocado y el update se va a la app de otro año.
    """
    otra = next(i for i in sorted(app_ids_configurados()) if i != str(servicio.app_id))
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Basic(otra))

    with pytest.raises(EscrituraFueraDeEntorno) as e:
        servicio.update_item(123, {"x": 1})

    assert otra in str(e.value) and str(servicio.app_id) in str(e.value)
    assert prohibir_escrituras == []


@pytest.mark.skipif(APP_ENV != "test", reason="el match estricto exige la bandera")
def test_update_al_item_de_su_propia_app_si_pasa(servicio, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Basic(str(servicio.app_id)))
    # No debe levantar.
    servicio._verificar_escritura_permitida("UPDATE", item_id=123)


@pytest.mark.skipif(APP_ENV != "test", reason="el match estricto exige la bandera")
def test_si_no_se_puede_verificar_el_item_NO_se_escribe(servicio, monkeypatch):
    """Fail-closed: perder una sync en dev es barato; escribir en prod no."""
    def _get_que_falla(*a, **k):
        raise requests.exceptions.ConnectionError("sin red")

    monkeypatch.setattr(requests, "get", _get_que_falla)
    with pytest.raises(EscrituraFueraDeEntorno):
        servicio._verificar_escritura_permitida("UPDATE", item_id=999)


# ---------------------------------------------------------------- servicio RO

@pytest.mark.parametrize("operacion", ["create", "update", "delete"])
def test_el_servicio_de_solo_lectura_no_escribe_ni_con_las_banderas_apagadas(
        monkeypatch, prohibir_escrituras, operacion):
    _con_readonly(monkeypatch, False)
    ids = sorted(app_ids_configurados())
    svc = PodioReadOnlyService("QID", ids[0], year=2026)
    monkeypatch.setattr(svc, "_headers", lambda: {"Authorization": "OAuth2 falso"})

    with pytest.raises(EscrituraPodioBloqueada):
        if operacion == "create":
            svc.create_item({"x": 1})
        elif operacion == "update":
            svc.update_item(1, {"x": 1})
        else:
            svc.delete_item("1")

    assert prohibir_escrituras == []


def test_el_servicio_de_solo_lectura_si_lee(monkeypatch):
    ids = sorted(app_ids_configurados())
    svc = PodioReadOnlyService("QID", ids[0], year=2026)
    monkeypatch.setattr(svc, "_headers", lambda: {"Authorization": "OAuth2 falso"})

    class _R:
        def raise_for_status(self): return None
        def json(self): return {"items": [], "filtered": 3, "total": 3}

    monkeypatch.setattr(requests, "post", lambda *a, **k: _R())
    assert svc.get_items_page(limit=1)["total"] == 3


def test_el_router_entrega_un_servicio_de_solo_lectura():
    from src.podio.services.job_services import podio_jobs_router

    svc = podio_jobs_router.get_readonly_service("QID", 2026)
    assert isinstance(svc, PodioReadOnlyService)
    # Mismas credenciales que el servicio normal: no es otra resolución.
    assert svc.app_id == podio_jobs_router.get_service("QID", 2026).app_id
