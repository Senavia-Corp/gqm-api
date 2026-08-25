"""Una fila "resuelta" cuyo fichero no esta tiene que poder reintentarse.

El panel las señala —"7 de estas 13 figuran resueltas y su fichero sigue sin
estar"— pero no habia forma de recuperarlas: el endpoint devolvia
"Already resolved" y el boton solo aparecia cuando `resolved` era False. O sea,
se las marcaba como perdidas y la unica salida era DELETE, que borra el
inventario de lo que falta.

Medido en produccion el 25-ago-2026, DESPUES de desplegar los arreglos: de las
13 filas, 6 se recuperaron de verdad al pulsar Resync (ids 7-11 y 13, con sus
ficheros ya en `attachments`) y 7 siguen sin fichero — las de agosto, que
figuran resueltas desde entonces.

El reintento NO se abre a cualquier resuelta: solo a las que mienten de forma
medible.
"""
from contextlib import contextmanager

import pytest

import src.routes.Webhook_bp as wb

RESYNC = wb.resync_failed_sync.__wrapped__


class _Falla:
    def __init__(self, resolved=True):
        self.id = 1
        self.resolved = resolved
        self.item_id = "3321543437"
        self.hook_type = "podio.jobs.QID.2026.file.change"
        self.error_message = "fallo original"
        self.payload = {"type": "file.change", "item_id": self.item_id,
                        "action_type": "file_created",
                        "file_ids": "2483721695"}


class _Job:
    ID_Jobs = "QID61309"
    podio_app_year = 2026


class _Sesion:
    def __init__(self, falla):
        self.falla = falla
        self.commits = 0

    def get(self, _m, _i):
        return self.falla

    def exec(self, _s):
        return self

    def first(self):
        return _Job()

    def add(self, _o):
        pass

    def commit(self):
        self.commits += 1


@pytest.fixture
def correr(monkeypatch, app):
    huellas = {"reintentos": 0}

    def _pfce(**kwargs):
        huellas["reintentos"] += 1

    import src.utils.podio_webhook_core as core
    monkeypatch.setattr(core, "process_file_change_event", _pfce)

    def _correr(falla, pendientes):
        sesion = _Sesion(falla)

        @contextmanager
        def _gs():
            yield sesion

        monkeypatch.setattr(wb, "get_session", _gs)
        monkeypatch.setattr(
            wb, "_adjuntos_pendientes", lambda _p: list(pendientes))

        with app.test_request_context(json={}):
            resp, codigo = RESYNC(falla.id)
        return resp.get_json(), codigo, huellas

    return _correr


def test_una_resuelta_que_miente_si_se_reintenta(correr):
    """EL CASO DE LAS 7: el panel las denuncia y no se podian recuperar."""
    _, codigo, huellas = correr(_Falla(resolved=True), ["2483721695"])

    assert huellas["reintentos"] == 1, (
        "sigue devolviendo 'Already resolved' a una fila cuyo fichero falta: "
        "el panel la señala como perdida y no hay forma de recuperarla")
    assert codigo == 502, "el fichero seguia faltando; no puede cerrar en verde"


def test_una_resuelta_de_verdad_no_se_reintenta(correr):
    """No abrir el reintento a cualquier resuelta: solo a las que mienten."""
    cuerpo, codigo, huellas = correr(_Falla(resolved=True), [])

    assert codigo == 200
    assert cuerpo["status"] == "Already resolved"
    assert huellas["reintentos"] == 0, "reintento una falla ya resuelta de verdad"


def test_una_abierta_sigue_reintentandose(correr):
    """Regresion: el camino normal no cambia."""
    _, _, huellas = correr(_Falla(resolved=False), [])
    assert huellas["reintentos"] == 1


def test_al_recuperarse_de_verdad_cierra_en_verde(correr):
    falla = _Falla(resolved=True)
    _, codigo, huellas = correr(falla, ["2483721695"])
    assert huellas["reintentos"] == 1

    # segunda pasada: ahora el fichero si esta
    _, codigo2, _ = correr(falla, [])
    assert codigo2 == 200
