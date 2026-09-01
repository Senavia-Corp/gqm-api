"""B2: SECRET_KEY enlazado, whitelist cerrada y token de webhooks (REG-007/018/019/032/096)."""
from decouple import config

from tests.fixtures.podio_items import qid_item


def test_webhook_without_token_is_rejected(client):
    resp = client.post(
        "/webhook/podio/jobs/QID/2026",
        json={"type": "item.create", "item_id": 1, "item": qid_item()},
    )
    assert resp.status_code == 403


def test_webhook_wrong_token_is_rejected(client):
    resp = client.post(
        "/webhook/podio/jobs/QID/2026?token=nope",
        json={"type": "item.create", "item_id": 1, "item": qid_item()},
    )
    assert resp.status_code == 403


def test_failed_syncs_requires_auth(client):
    # Gestión de fallos ya no es pública (contiene detalle operativo)
    assert client.get("/webhook/podio/failed_syncs").status_code == 401


def test_podio_debug_requires_auth(client):
    # Antes el prefijo /podio de la whitelist exponía el dump de debug
    assert client.get("/podio/items/QID?year=2026").status_code == 401


def test_qbo_connect_requires_auth(client):
    assert client.get("/qbo/connect").status_code == 401


def test_qbo_connect_session_works_with_secret_key(client, admin_headers):
    # REG-007: sin app.secret_key esto era un 500 (NullSession)
    resp = client.get("/qbo/connect", headers=admin_headers)
    assert resp.status_code == 302
    assert "appcenter.intuit.com" in resp.headers.get("Location", "")


def test_sync_routes_require_auth(client):
    assert client.get("/sync_podio/jobs/QID/2026").status_code in (401, 404)
    # el prefijo /sync ya no está en la whitelist: cualquier ruta bajo él exige JWT


# ── Endpoints nuevos del cutover de webhooks ────────────────────────────────
#
# Los tres escriben en Podio de produccion: registran hooks, piden
# verificaciones y BORRAN hooks por id. Que hereden `admin:sync` de
# `protect_blueprint` es cierto por como funciona (un before_request sobre el
# blueprint entero, no una enumeracion de rutas), pero razonarlo no basta: un
# DELETE de hooks abierto seria un apagon de la sincronizacion al alcance de
# cualquiera. Se mide.

def test_register_hooks_requires_auth(client):
    assert client.post("/admin/webhooks/QID/register?year=2026").status_code == 401


def test_verify_hook_requires_auth(client):
    assert client.post("/admin/webhooks/QID/verify/1?year=2026").status_code == 401


def test_delete_hook_requires_auth(client):
    """El mas peligroso de los tres: borrar los hooks mata la sync entrante."""
    assert client.delete("/admin/webhooks/QID/hook/1?year=2026").status_code == 401


def test_clear_hooks_requires_auth(client):
    assert client.delete("/admin/webhooks/QID/clear?year=2026").status_code == 401


def test_listar_hooks_requires_auth(client):
    assert client.get("/admin/webhooks/QID?year=2026").status_code == 401
