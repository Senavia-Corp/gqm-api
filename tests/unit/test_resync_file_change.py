"""12 de las 13 filas vivas son `file.change` y no habia rama que las reintentara.

Tres defectos de la misma funcion, que hay que tocar juntos:

(a) El `return 422` de `file.change` estaba DENTRO del
    `if len(parts)>=5 and parts[1]=="jobs"`, asi que Python salia antes de la
    cadena de `elif` de mas abajo: ninguna rama colocada ahi podia alcanzarlo
    jamas. Y la unica salida que quedaba era DELETE, que borra la evidencia de
    un fichero que sigue faltando.

(b) `_cascade_delete_job_from_podio(session, item_id)` perdia `app_type`, que
    estaba vivo dos lineas mas arriba. Sin el, el `if job_id and app_type` de la
    cascada no entra: la confirmacion contra Podio NO CORRE y el job se borra
    con todos sus hijos sin preguntar.

(c) Se decidia borrar con `any(c in str(podio_err) for c in ("404","410"))`, una
    SUBCADENA sobre el texto del error. Un mensaje que la contenga por
    casualidad —una URL, un id, un timestamp— disparaba un borrado en cascada.
"""
import inspect
from contextlib import contextmanager

import pytest

import src.routes.Webhook_bp as wb
import src.utils.podio_webhook_core as core

RESYNC = wb.resync_failed_sync.__wrapped__
# getattr: sin el arreglo este endpoint no existe, y un ImportError haria que el
# fichero ENTERO no se recolectase — la demostracion contra el baseline dejaria
# de probar los defectos (a), (b) y (c). Asi cada test falla por lo suyo.
RESOLVER = getattr(getattr(wb, "resolver_failed_sync", None), "__wrapped__", None)


def _exige_resolver():
    assert RESOLVER is not None, (
        "no hay endpoint para cerrar una falla recuperada por fuera: la unica "
        "salida sigue siendo DELETE, que borra el inventario de lo perdido")


class _Falla:
    def __init__(self, hook_type="podio.jobs.QID.2026.file.change",
                 accion="file_created", file_ids="2483721695"):
        self.id = 1
        self.resolved = False
        self.item_id = "3321543437"
        self.hook_type = hook_type
        self.error_message = "fallo original"
        self.payload = {"type": "file.change", "item_id": self.item_id,
                        "action_type": accion, "file_ids": file_ids}


class _Job:
    ID_Jobs = "QID61309"
    podio_item_id = "3321543437"


class _Sesion:
    def __init__(self, falla, job=_Job()):
        self.falla, self.job = falla, job
        self.commits = 0

    def get(self, _m, _i):
        return self.falla

    def exec(self, _s):
        return self

    def first(self):
        return self.job

    def add(self, _o):
        pass

    def commit(self):
        self.commits += 1


@pytest.fixture
def escenario(monkeypatch, app):
    """Devuelve correr(falla, pendientes, job) -> (cuerpo, codigo, huellas)."""
    huellas = {"process_file_change_event": [], "cascade": []}

    def _pfce(**kwargs):
        huellas["process_file_change_event"].append(kwargs)

    monkeypatch.setattr(core, "process_file_change_event", _pfce)

    def _cascade(session, item_id, *, app_type, year=None):
        huellas["cascade"].append((item_id, app_type, year))
        return ("QID61309", 0, 0)

    monkeypatch.setattr(wb, "_cascade_delete_job_from_podio", _cascade)

    def correr(falla, pendientes=(), job=_Job(), fn=RESYNC):
        sesion = _Sesion(falla, job)

        @contextmanager
        def _gs():
            yield sesion

        monkeypatch.setattr(wb, "get_session", _gs)
        # raising=False: sin el arreglo este helper no existe. Sin esto el test
        # moriria aqui en vez de en el assert, y la demostracion contra el
        # baseline no probaria el defecto.
        monkeypatch.setattr(
            wb, "_adjuntos_pendientes", lambda _p: list(pendientes),
            raising=False)

        with app.test_request_context(json={}):
            resp, codigo = fn(falla.id)
        return resp.get_json(), codigo, huellas

    return correr


# --------------------------------------------------------------------------
# (a) file.change se reintenta de verdad
# --------------------------------------------------------------------------
def test_file_change_se_reintenta_en_vez_de_rendirse(escenario):
    cuerpo, codigo, huellas = escenario(_Falla())

    assert huellas["process_file_change_event"], (
        "`file.change` sigue sin reintentarse: 12 de 13 filas se quedan fuera")
    assert codigo == 200, cuerpo


def test_el_reintento_usa_el_job_y_el_ano_del_hook(escenario):
    _, _, huellas = escenario(_Falla("podio.jobs.PAR.2025.file.change"))
    kwargs = huellas["process_file_change_event"][0]
    assert kwargs["app_type"] == "PAR"
    assert kwargs["year"] == 2025
    assert kwargs["id_jobs"] == "QID61309"


def test_no_cierra_si_el_adjunto_sigue_sin_estar(escenario):
    """Lo que separa esto de las 7 filas resueltas en falso."""
    cuerpo, codigo, _ = escenario(_Falla(), pendientes=["2483721695"])

    assert codigo == 502, "cerro una falla con el fichero todavia perdido"
    assert cuerpo["file_ids_pendientes"] == ["2483721695"]


def test_sin_job_en_la_bd_lo_dice_en_vez_de_reintentar(escenario):
    _, codigo, huellas = escenario(_Falla(), job=None)
    assert codigo == 422
    assert not huellas["process_file_change_event"]


# --------------------------------------------------------------------------
# (b) la cascada recibe app_type en las dos rutas del resync
# --------------------------------------------------------------------------
def test_item_delete_pasa_el_app_type_a_la_cascada(escenario):
    _, codigo, huellas = escenario(
        _Falla("podio.jobs.QID.2026.item.delete", accion=None))
    assert huellas["cascade"] == [("3321543437", "QID", 2026)], (
        "la cascada corrio sin app_type: borra sin confirmar contra Podio")
    assert codigo == 200


def test_app_type_es_obligatorio_y_por_nombre():
    firma = inspect.signature(wb._cascade_delete_job_from_podio)
    p = firma.parameters["app_type"]
    assert p.default is inspect.Parameter.empty
    assert p.kind is inspect.Parameter.KEYWORD_ONLY


# --------------------------------------------------------------------------
# (c) se le pregunta a Podio, no al texto del error
# --------------------------------------------------------------------------
@pytest.mark.parametrize("vivo,debe_borrar", [
    (False, True),    # Podio confirma que ya no esta -> converger
    (True,  False),   # sigue vivo -> no tocar
    (None,  False),   # 5xx / timeout -> no lo se -> no tocar
])
def test_el_borrado_lo_decide_podio_no_la_subcadena(
        monkeypatch, app, escenario, vivo, debe_borrar):
    def _revienta(*a, **k):
        # Un mensaje que contiene "404" sin ser un 404: exactamente el caso
        # que la comparacion por subcadena convertia en borrado en cascada.
        raise RuntimeError("connection reset reading item 404123456789")

    monkeypatch.setattr(wb, "item_de_confianza", _revienta)
    monkeypatch.setattr(
        core, "item_sigue_vivo_en_podio", lambda *a, **k: vivo)

    falla = _Falla("podio.jobs.QID.2026.item.update", accion=None)
    # Cuando no se puede borrar, el `raise` vuelve a subir y el `except` ancho
    # del endpoint lo convierte en 500. Eso esta bien: la falla sigue abierta.
    _, codigo, huellas = escenario(falla)

    if debe_borrar:
        assert huellas["cascade"], "no convergio un item que Podio dice borrado"
        assert codigo == 200
    else:
        assert not huellas["cascade"], (
            f"borro en cascada con vivo={vivo}: el error solo CONTENIA '404'")
        assert codigo == 500


# --------------------------------------------------------------------------
# El endpoint para cerrar por fuera, sin borrar la evidencia
# --------------------------------------------------------------------------
def test_resolver_exige_prueba(escenario):
    _exige_resolver()
    cuerpo, codigo, _ = escenario(
        _Falla(), pendientes=["2483721695"], fn=RESOLVER)
    assert codigo == 409, "cerro una falla cuyo fichero sigue sin estar"
    assert cuerpo["file_ids_pendientes"] == ["2483721695"]


def test_resolver_cierra_cuando_el_fichero_si_esta(escenario):
    _exige_resolver()
    falla = _Falla()
    _, codigo, _ = escenario(falla, pendientes=[], fn=RESOLVER)
    assert codigo == 200
    assert falla.resolved is True


def test_resolver_no_reintenta_nada(escenario):
    _exige_resolver()
    _, _, huellas = escenario(_Falla(), pendientes=[], fn=RESOLVER)
    assert not huellas["process_file_change_event"], (
        "resolver debe COMPROBAR, no reintentar")
