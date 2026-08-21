"""El webhook no puede fiarse del `item` que venga en el cuerpo de la peticion.

Podio NO manda el item en sus webhooks: su payload lleva `type`, `item_id`,
`item_revision_id` y `hook_id`, nada mas. Asi que en produccion la rama
`data["item"]` solo puede activarla alguien que la ponga a mano.

Y mientras PODIO_WEBHOOK_TOKEN no este configurada el endpoint acepta SIN
autenticar (medido el 20-ago-2026: POST /webhook/podio/jobs/QID/2026 sin token
devuelve 200, no 403; ningun hook de produccion lleva token en la ruta). La
combinacion permitia sobrescribir cualquier job, campos de dinero incluidos.

Se sigue honrando con APP_ENV=test porque el arnes de integracion inyecta los
payloads por ahi y no tiene un Podio contra el que hablar.
"""
from unittest.mock import patch

from src.utils.get_podio_items import item_de_confianza

ITEM_FALSO = {"item_id": 1, "fields": [{"external_id": "money", "values": [{"value": "999999"}]}]}
ITEM_REAL = {"item_id": 1, "fields": [{"external_id": "money", "values": [{"value": "100"}]}]}


def test_en_produccion_ignora_el_item_del_cuerpo(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with patch("src.utils.get_podio_items.get_podio_item", return_value=ITEM_REAL) as traer:
        obtenido = item_de_confianza({"item": ITEM_FALSO}, 1, "QID")
    assert obtenido == ITEM_REAL, "el item inyectado NO debe usarse en produccion"
    traer.assert_called_once()


def test_sin_APP_ENV_tambien_ignora_el_cuerpo(monkeypatch):
    """Fallar cerrado: si la variable no esta, se asume produccion."""
    monkeypatch.delenv("APP_ENV", raising=False)
    with patch("src.utils.get_podio_items.get_podio_item", return_value=ITEM_REAL):
        assert item_de_confianza({"item": ITEM_FALSO}, 1, "QID") == ITEM_REAL


def test_en_test_si_honra_el_cuerpo(monkeypatch):
    """El arnes de integracion depende de esto."""
    monkeypatch.setenv("APP_ENV", "test")
    with patch("src.utils.get_podio_items.get_podio_item", return_value=ITEM_REAL) as traer:
        obtenido = item_de_confianza({"item": ITEM_FALSO}, 1, "QID")
    assert obtenido == ITEM_FALSO
    traer.assert_not_called()


def test_en_test_sin_item_en_el_cuerpo_va_a_podio(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    with patch("src.utils.get_podio_items.get_podio_item", return_value=ITEM_REAL) as traer:
        assert item_de_confianza({}, 1, "QID") == ITEM_REAL
    traer.assert_called_once()


def test_ninguna_ruta_del_webhook_lee_ya_el_item_del_cuerpo():
    """Guarda de regresion: que nadie reintroduzca el vector."""
    import pathlib
    src = (pathlib.Path(__file__).parents[2] / "src/routes/Webhook_bp.py").read_text()
    assert 'data.get("item")' not in src
    assert 'payload.get("item")' not in src
    assert src.count("item_de_confianza(") >= 5
