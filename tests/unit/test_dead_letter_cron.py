"""El cron que mantiene la dead-letter sin que nadie abra el panel.

Los dos barridos (`auto_marcar_irrecuperables` y el reconciliador de adjuntos
perdidos) colgaban de `GET /failed_syncs`: una falla no se etiquetaba hasta que
un humano miraba. Y los adjuntos perdidos en silencio no salen en el panel por
definicion, asi que abrirlo no los habria descubierto nunca.

Lo que se vigila aqui es el TOPE, que es la unica propiedad de seguridad real:
este cron escribe sin supervision, y un detector que se equivoque no puede
convertir su error en doscientas filas nuevas.
"""
from contextlib import contextmanager

import pytest

import src.routes.Webhook_bp as wb

CRON = wb.dead_letter_cron


@pytest.fixture
def sin_barrido(monkeypatch):
    """Neutraliza el marcado para aislar la mitad de adjuntos perdidos."""
    monkeypatch.setattr(wb, "auto_marcar_irrecuperables", lambda: 3)


def _montar(monkeypatch, filas, registrados):
    """Sesion falsa que devuelve `filas` y contador de registros."""
    class _Sesion:
        def exec(self, _stmt): return self
        def all(self): return filas

    @contextmanager
    def _get_session():
        yield _Sesion()

    monkeypatch.setattr(wb, "get_session", _get_session)

    import src.utils.failed_sync as fs
    monkeypatch.setattr(
        fs, "record_failed_attachment",
        lambda **kw: registrados.append(kw["file_id"]))


def _fila(job, file_id):
    # (id_jobs, file_id, visto, podio_item_id, podio_app_year)
    return (job, file_id, None, "3350842407", 2026)


def test_registra_lo_encontrado_por_debajo_del_tope(app, monkeypatch, sin_barrido):
    registrados = []
    _montar(monkeypatch, [_fila("QID61310", "2484212803"),
                          _fila("QID61285", "2484243251")], registrados)

    with app.test_request_context():
        cuerpo, codigo = CRON()

    datos = cuerpo.get_json()
    assert codigo == 200
    assert datos["perdidos_detectados"] == 2
    assert datos["perdidos_registrados"] == 2
    assert datos["plantado"] is False
    assert registrados == ["2484212803", "2484243251"]


def test_por_encima_del_tope_se_planta_SIN_registrar(app, monkeypatch, sin_barrido):
    """La propiedad que importa: si el detector se vuelve loco, el cron avisa en
    vez de inundar la tabla. Registrar de mas es barato de crear y caro de
    limpiar, y ademas entierra las fallas de verdad."""
    monkeypatch.setattr(wb, "TOPE_DEAD_LETTER_CRON", 2)
    registrados = []
    _montar(monkeypatch, [_fila("QID6100%d" % i, str(i)) for i in range(5)],
            registrados)

    with app.test_request_context():
        cuerpo, codigo = CRON()

    datos = cuerpo.get_json()
    assert codigo == 200, "un cron que revienta se convierte en ruido de alertas"
    assert datos["plantado"] is True
    assert datos["perdidos_detectados"] == 5
    assert datos["perdidos_registrados"] == 0
    assert registrados == [], "se planto pero registro igual"


def test_el_marcado_corre_aunque_falle_la_reconciliacion(app, monkeypatch):
    """Son dos trabajos independientes: que uno se caiga no puede llevarse el
    otro por delante."""
    monkeypatch.setattr(wb, "auto_marcar_irrecuperables", lambda: 4)

    @contextmanager
    def _revienta():
        raise RuntimeError("la BD dijo que no")
        yield  # pragma: no cover

    monkeypatch.setattr(wb, "get_session", _revienta)

    with app.test_request_context():
        cuerpo, codigo = CRON()

    assert codigo == 200
    assert cuerpo.get_json()["marcadas_irrecuperables"] == 4


def test_la_reconciliacion_corre_aunque_falle_el_marcado(app, monkeypatch):
    def _revienta():
        raise RuntimeError("no se pudo marcar")

    monkeypatch.setattr(wb, "auto_marcar_irrecuperables", _revienta)
    registrados = []
    _montar(monkeypatch, [_fila("QID61310", "2484212803")], registrados)

    with app.test_request_context():
        cuerpo, codigo = CRON()

    assert codigo == 200
    assert cuerpo.get_json()["perdidos_registrados"] == 1


def test_el_cron_esta_en_vercel_json():
    """Un endpoint de cron que nadie invoca es codigo muerto."""
    import json
    crons = json.load(open("vercel.json"))["crons"]
    rutas = [c["path"] for c in crons]
    assert "/webhook/podio/dead_letter_cron" in rutas
