"""`podio.attachment.file_deleted` es una BAJA: reintentarla es borrar, no anadir.

La rama que el PR #123 anadio al resync capturaba los CUATRO action_type por
igual y los mandaba todos a `sync_job_attachments_by_id`, que SOLO ANADE — un
grep de delete/remove/borr sobre sync_attachments.py da cero aciertos. Y su
comprobacion (`if not llego: 502`) pregunta al reves para un borrado: que el
fichero SIGA en la tabla es el fracaso, no el exito.

O sea, reintentar un `file_deleted` lo cerraba como resuelto con el fichero
todavia vivo — exactamente la mentira que el guard de `file.change` mato.

Es producible: `failed_sync.py:63` monta el hook_type con el action_type y
`podio_webhook_core.py:473` lo invoca desde el `except` de esa rama.

Funcionales a proposito: un test de AST no distingue "comprueba la tabla" de
"comprueba la tabla AL REVES", que es justo el defecto.
"""
from contextlib import contextmanager

import pytest

import src.routes.Webhook_bp as wb
import src.cloudinary.service as cloudinary_service

# `resync_failed_sync` va decorado con @require_permission, que usa @wraps:
# `__wrapped__` es la funcion desnuda. Asi se prueba la logica sin montar IAM.
RESYNC = wb.resync_failed_sync.__wrapped__


class _Falla:
    """Doble de PodioFailedSync."""

    def __init__(self, action_type="file_deleted", **extra):
        self.id = 1
        self.resolved = False
        self.item_id = "3304340068"
        self.hook_type = f"podio.attachment.{action_type}"
        self.payload = {
            "file_id": "999",
            "action_type": action_type,
            "fk_field": "ID_Jobs",
            "fk_value": "QID61359",
            **extra,
        }


class _Adjunto:
    """Doble de Attachments con identidad persistida (el caso mayoritario)."""

    Link = "https://res.cloudinary.com/gqm/raw/upload/v1/Jobs/QID/QID61359/f.pdf"
    cloudinary_public_id = "Jobs/QID/QID61359/f_e0cddbeb.pdf"
    cloudinary_resource_type = "raw"


class _Job:
    """Doble de Job: la rama de ALTA lo necesita para sacar el año."""

    ID_Jobs = "QID61359"
    podio_app_year = 2026


class _Sesion:
    """Una sola sesion compartida: asi la comprobacion de ausencia ve el borrado.

    `fila` es el estado de la tabla; `delete()` lo vacia, que es lo que la
    comprobacion posterior tiene que observar.

    `exec` mira a que tabla apunta el SELECT porque el endpoint consulta Job y
    Attachments con la misma sesion; devolver siempre lo mismo confundiria las
    dos ramas.
    """

    def __init__(self, falla, fila):
        self.falla, self.fila = falla, fila
        self.borradas, self.commits = [], 0
        self._ultimo = ""

    def get(self, _modelo, _id):
        return self.falla

    def exec(self, stmt):
        self._ultimo = str(stmt).lower()
        return self

    def first(self):
        if " jobs" in self._ultimo and "attachments" not in self._ultimo:
            return _Job()
        return self.fila

    def delete(self, obj):
        self.borradas.append(obj)
        self.fila = None

    def add(self, _obj):
        pass

    def commit(self):
        self.commits += 1


@pytest.fixture
def escenario(monkeypatch, app):
    """Monta el endpoint con sesion doble y Cloudinary fingido.

    Devuelve una funcion `correr(falla, fila, veredicto)` -> (cuerpo, codigo).
    """
    llamadas = {"sync_job_attachments_by_id": 0, "destroy": []}

    def _sync_falso(**kwargs):
        llamadas["sync_job_attachments_by_id"] += 1
        return {"created": 0, "skipped": 0}

    import src.podio.sync.sync_attachments as sync_attachments
    monkeypatch.setattr(
        sync_attachments, "sync_job_attachments_by_id", _sync_falso)

    def correr(falla, fila=None, veredicto="ok"):
        sesion = _Sesion(falla, fila)

        @contextmanager
        def _get_session():
            yield sesion

        monkeypatch.setattr(wb, "get_session", _get_session)

        def _destroy(public_id, resource_type):
            llamadas["destroy"].append((public_id, resource_type))
            return veredicto

        # raising=False a proposito: sin el arreglo este nombre no existe, y
        # el test debe morir en el ASSERT (el defecto), no en el monkeypatch.
        monkeypatch.setattr(
            cloudinary_service, "destroy_en_cloudinary", _destroy, raising=False)

        with app.test_request_context():
            resp, codigo = RESYNC(falla.id)
        return resp.get_json(), codigo, sesion

    correr.llamadas = llamadas
    return correr


# --------------------------------------------------------------------------
# El defecto: una baja no se reintenta anadiendo
# --------------------------------------------------------------------------
def test_file_deleted_no_va_al_sincronizador_que_solo_anade(escenario):
    """`sync_job_attachments_by_id` no borra nada: mandarlo ahi es cerrar en falso."""
    _, codigo, _ = escenario(_Falla("file_deleted"), fila=_Adjunto())

    assert escenario.llamadas["sync_job_attachments_by_id"] == 0, (
        "un borrado fallido se mando al camino que SOLO ANADE")
    assert codigo == 200


def test_file_deleted_borra_en_cloudinary_y_en_la_tabla(escenario):
    fila = _Adjunto()
    cuerpo, codigo, sesion = escenario(_Falla("file_deleted"), fila=fila)

    assert escenario.llamadas["destroy"] == [
        ("Jobs/QID/QID61359/f_e0cddbeb.pdf", "raw")], (
        "no uso la identidad persistida para borrar")
    assert sesion.borradas == [fila], "la fila sigue en la tabla"
    assert codigo == 200, cuerpo


def test_file_deleted_no_cierra_si_el_fichero_sigue_ahi(app, monkeypatch):
    """La comprobacion de un borrado es AUSENCIA. Si sigue, la falla sigue abierta."""
    class _SesionQueNoBorra(_Sesion):
        def delete(self, obj):
            self.borradas.append(obj)        # ...pero `fila` NO se vacia

    falla, fila = _Falla("file_deleted"), _Adjunto()
    sesion = _SesionQueNoBorra(falla, fila)

    @contextmanager
    def _get_session():
        yield sesion

    monkeypatch.setattr(wb, "get_session", _get_session)
    monkeypatch.setattr(
        cloudinary_service, "destroy_en_cloudinary", lambda *a: "ok",
        raising=False)

    with app.test_request_context():
        resp, codigo = RESYNC(falla.id)

    assert codigo == 502, "cerro un borrado que no ocurrio"
    assert resp.get_json()["resuelto"] is False
    assert falla.resolved is False, "marco resuelto una falla viva"


def test_cloudinary_not_found_es_exito_al_reintentar(escenario):
    """Reintentando, "not found" significa que ya no esta: es lo que se pedia."""
    _, codigo, _ = escenario(
        _Falla("file_deleted"), fila=_Adjunto(), veredicto="not found")
    assert codigo == 200


def test_cloudinary_que_no_confirma_no_cierra_la_falla(escenario):
    cuerpo, codigo, sesion = escenario(
        _Falla("file_deleted"), fila=_Adjunto(), veredicto="error")
    assert codigo == 502, cuerpo
    assert sesion.borradas == [], "borro la fila sin que Cloudinary confirmara"


def test_la_fila_ya_borrada_converge(escenario):
    """Sin fila y sin fichero, el borrado ya ocurrio: resolver es correcto."""
    _, codigo, _ = escenario(_Falla("file_deleted"), fila=None)
    assert codigo == 200
    assert escenario.llamadas["destroy"] == []


# --------------------------------------------------------------------------
# Limite de confianza: fk_field llega del payload y acaba en un getattr
# --------------------------------------------------------------------------
@pytest.mark.parametrize("fk_field", ["ID_Client", "__class__", "Link", ""])
def test_rechaza_un_fk_field_que_no_es_columna(escenario, fk_field):
    falla = _Falla("file_deleted")
    falla.payload["fk_field"] = fk_field
    _, codigo, _ = escenario(falla, fila=_Adjunto())
    assert codigo == 422, f"acepto fk_field={fk_field!r} en un getattr"


# --------------------------------------------------------------------------
# Regresion: las ALTAS siguen yendo por donde iban
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "accion", ["file_created", "file_replaced", "item_attachments"])
def test_las_altas_siguen_usando_el_sincronizador(escenario, accion):
    escenario(_Falla(accion), fila=_Adjunto())
    assert escenario.llamadas["sync_job_attachments_by_id"] == 1, (
        f"{accion} dejo de reintentarse por el camino de alta")
    assert escenario.llamadas["destroy"] == [], f"{accion} borro algo"
