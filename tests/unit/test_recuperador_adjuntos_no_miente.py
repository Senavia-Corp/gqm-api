"""`POST /sync_podio/phase2/jobs/attachments/<id>` respondia ✅ sin recuperar nada.

`process_item_attachments` se tragaba cada fallo por fichero con
`record_failed_attachment(...)` + `continue` y no devolvia NADA, asi que
`sync_job_attachments_by_id` deducia `created` restando longitudes (after -
before) — que no distingue "no habia nada que crear" de "fallaron los tres" — y
la ruta respondia 200 "Attachments del Job sincronizados ✅" pasara lo que
pasara.

Importa mas de lo que parece: ese endpoint es el procedimiento que el 422 del
resync le indica al operador, y su respuesta es la unica senal que tiene.
Mientras mienta, NADA que dependa de adjuntos se puede verificar.
"""
from contextlib import contextmanager

import pytest

import src.utils.podio_webhook_core as core


class _Respuesta:
    headers = {"Content-Type": "application/pdf"}
    content = b"%PDF-1.4 fake"

    def raise_for_status(self):
        pass


class _Sesion:
    """Sesion doble: la tabla empieza vacia, asi que nada se omite por duplicado."""

    def __init__(self):
        self.anadidos = []

    def exec(self, _stmt):
        return self

    def first(self):
        return None

    def add(self, obj):
        self.anadidos.append(obj)

    def commit(self):
        pass

    @contextmanager
    def begin_nested(self):
        yield


@pytest.fixture
def entorno(monkeypatch):
    """Deja `process_item_attachments` ejercitable sin Podio ni Cloudinary."""
    monkeypatch.setattr(core, "get_podio_headers", lambda *a, **k: {})
    monkeypatch.setattr(core.requests, "get", lambda *a, **k: _Respuesta())
    monkeypatch.setattr(core, "generate_custom_id", lambda *a, **k: "ATT99999")
    # `record_failed_attachment` abre sesion propia contra la BD: aqui solo
    # interesa que no estorbe, los conteos son lo que se mide.
    monkeypatch.setattr(core, "record_failed_attachment", lambda **k: None)
    return monkeypatch


FICHEROS = [{"file_id": 1, "name": "a.pdf"},
            {"file_id": 2, "name": "b.pdf"},
            {"file_id": 3, "name": "c.pdf"}]


# --------------------------------------------------------------------------
# 1. La funcion cuenta lo que pasa
# --------------------------------------------------------------------------
def test_si_cloudinary_revienta_los_cuenta_como_fallidos(entorno):
    def _explota(**kwargs):
        raise RuntimeError("Cloudinary caido")

    entorno.setattr(core, "upload_to_cloudinary", _explota)

    r = core.process_item_attachments(
        session=_Sesion(), files=FICHEROS, app_type="QID",
        year=2026, id_jobs="QID61359")

    assert r["fallidos"] == 3, "se trago los tres fallos"
    assert r["creados"] == 0
    assert sorted(r["file_ids_fallidos"]) == ["1", "2", "3"]


def test_cuando_todo_va_bien_los_cuenta_como_creados(entorno):
    entorno.setattr(core, "upload_to_cloudinary", lambda **k: {
        "secure_url": "https://res.cloudinary.com/x/raw/upload/v1/a.pdf",
        "format": "pdf", "public_id": "a", "resource_type": "raw"})

    r = core.process_item_attachments(
        session=_Sesion(), files=FICHEROS, app_type="QID",
        year=2026, id_jobs="QID61359")

    assert (r["creados"], r["fallidos"]) == (3, 0), r


def test_sin_ficheros_no_inventa_nada(entorno):
    r = core.process_item_attachments(
        session=_Sesion(), files=[], app_type="QID", id_jobs="QID61359")
    assert r == {"creados": 0, "omitidos": 0, "fallidos": 0,
                 "file_ids_fallidos": []}


def test_un_app_type_sin_sitio_donde_colgar_no_es_un_exito(entorno):
    """Sin FK no se guarda NINGUNO. Contarlos como omitidos daria un 200."""
    r = core.process_item_attachments(
        session=_Sesion(), files=FICHEROS, app_type="DESCONOCIDA",
        entity_id="X1")
    assert r["fallidos"] == 3, "un app_type sin mapear se dio por bueno"


# --------------------------------------------------------------------------
# 2. La ruta deja de responder ✅
# --------------------------------------------------------------------------
def _llamar_ruta(monkeypatch, app, resultado):
    import src.routes.podio_routes.sync_routes as sync_routes

    monkeypatch.setattr(
        sync_routes, "sync_job_attachments_by_id", lambda **k: resultado)
    ruta = sync_routes.sync_job_attachments_by_id_route.__wrapped__

    with app.test_request_context("/?year=2026"):
        resp, codigo = ruta("QID61359")
    return resp.get_json(), codigo


def test_la_ruta_no_dice_ok_si_fallo_algo(monkeypatch, app):
    cuerpo, codigo = _llamar_ruta(monkeypatch, app, {
        "processed": 3, "created": 0, "skipped": 0,
        "fallidos": 3, "file_ids_fallidos": ["1", "2", "3"]})

    assert codigo != 200, "sigue diciendo ✅ con los tres ficheros perdidos"
    assert "✅" not in cuerpo["message"]
    assert cuerpo["file_ids_fallidos"] == ["1", "2", "3"], (
        "no dice CUALES fallaron, que es lo que el operador necesita")


def test_un_exito_parcial_se_distingue_de_un_fracaso_total(monkeypatch, app):
    _, parcial = _llamar_ruta(monkeypatch, app, {
        "processed": 3, "created": 2, "skipped": 0,
        "fallidos": 1, "file_ids_fallidos": ["3"]})
    _, total = _llamar_ruta(monkeypatch, app, {
        "processed": 3, "created": 0, "skipped": 0,
        "fallidos": 3, "file_ids_fallidos": ["1", "2", "3"]})

    assert parcial == 207 and total == 502, (parcial, total)


def test_cuando_de_verdad_fue_bien_sigue_respondiendo_ok(monkeypatch, app):
    """Regresion: el camino bueno no debe cambiar."""
    cuerpo, codigo = _llamar_ruta(monkeypatch, app, {
        "processed": 2, "created": 2, "skipped": 0,
        "fallidos": 0, "file_ids_fallidos": []})
    assert codigo == 200
    assert "✅" in cuerpo["message"]
