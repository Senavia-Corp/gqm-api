"""La ventana de gracia del cutover de PODIO_WEBHOOK_TOKEN.

Por que existe: los 48 hooks de PRODUCCION estan registrados SIN token en la
ruta. Definir PODIO_WEBHOOK_TOKEN los deja a todos en 403, y un 403 aqui es
perdida DEFINITIVA — Podio solo reintenta los 5xx, el 403 sale del
before_request antes de que nada llegue a `podio_failed_syncs`, y Podio ademas
desactiva los hooks que fallan de forma persistente.

Lo que estos tests fijan es justo lo que hace segura la gracia. Si alguno se
rompe, la ventana deja de ser una ventana:

  * caduca sola          -> el agujero se cierra aunque nadie la retire
  * falla cerrado        -> un valor ilegible NO concede gracia
  * solo cubre la ausencia -> un token EQUIVOCADO sigue dando 403
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.routes.Webhook_bp import _gracia_de_cutover_vigente

VAR = "PODIO_WEBHOOK_TOKEN_GRACIA_HASTA"


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat()


def test_sin_variable_no_hay_gracia(monkeypatch):
    """El estado por defecto: sin la variable, el comportamiento es el de siempre."""
    monkeypatch.delenv(VAR, raising=False)
    assert _gracia_de_cutover_vigente() is False


def test_ventana_futura_concede_gracia(monkeypatch):
    monkeypatch.setenv(VAR, _iso(timedelta(hours=4)))
    assert _gracia_de_cutover_vigente() is True


def test_ventana_pasada_no_concede_gracia(monkeypatch):
    """Caduca sola: es lo que impide que un olvido deje el agujero abierto."""
    monkeypatch.setenv(VAR, _iso(timedelta(minutes=-1)))
    assert _gracia_de_cutover_vigente() is False


@pytest.mark.parametrize("valor", ["", "   ", "manana", "2026-13-45", "1788283028"])
def test_valor_ilegible_falla_cerrado(monkeypatch, valor):
    """Un timestamp mal escrito no puede abrir la puerta por accidente."""
    monkeypatch.setenv(VAR, valor)
    assert _gracia_de_cutover_vigente() is False


def test_sufijo_z_y_sin_offset_se_leen_como_utc(monkeypatch):
    """`...Z` y una fecha sin offset son las dos formas que se van a escribir a mano."""
    futuro = datetime.now(timezone.utc) + timedelta(hours=4)
    monkeypatch.setenv(VAR, futuro.strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert _gracia_de_cutover_vigente() is True

    monkeypatch.setenv(VAR, futuro.strftime("%Y-%m-%dT%H:%M:%S"))  # sin tz → UTC
    assert _gracia_de_cutover_vigente() is True

    pasado = datetime.now(timezone.utc) - timedelta(hours=1)
    monkeypatch.setenv(VAR, pasado.strftime("%Y-%m-%dT%H:%M:%S"))
    assert _gracia_de_cutover_vigente() is False, (
        "una fecha sin offset debe leerse como UTC; si se leyera como hora local, "
        "la gracia se concederia o se negaria con horas de desfase")


# ── La puerta entera, sobre el receptor real ────────────────────────────────
# Los dos casos que separan una ventana de gracia de un agujero abierto.

def test_gracia_deja_pasar_una_entrega_SIN_token(client, monkeypatch):
    monkeypatch.setenv("PODIO_WEBHOOK_TOKEN", "a" * 48)
    monkeypatch.setenv(VAR, _iso(timedelta(hours=4)))
    resp = client.post("/webhook/podio/jobs/QID/2026",
                       json={"type": "hook.ping", "item_id": 1})
    assert resp.status_code != 403, (
        "con la gracia vigente, un hook legado sin token NO puede recibir 403: "
        "es exactamente la entrega que se perderia para siempre")


def test_gracia_NO_cubre_un_token_equivocado(client, monkeypatch):
    monkeypatch.setenv("PODIO_WEBHOOK_TOKEN", "a" * 48)
    monkeypatch.setenv(VAR, _iso(timedelta(hours=4)))
    resp = client.post("/webhook/podio/jobs/QID/2026/" + "b" * 48,
                       json={"type": "hook.ping", "item_id": 1})
    assert resp.status_code == 403, (
        "la gracia solo cubre la AUSENCIA de token; si tapara tambien un token "
        "equivocado, seria un bypass de autenticacion, no una ventana")
