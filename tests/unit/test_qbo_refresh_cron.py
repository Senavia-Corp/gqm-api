"""El cron de refresco de tokens de QBO falla CERRADO.

Sin este cron el refresh token de Intuit muere a los ~100 dias de inactividad
del realm y nadie se entera. Mismo patron que Paridad.reconciliar_cron: valida
su propio CRON_SECRET porque Vercel Cron manda GET con Bearer <secreto>, que no
es un JWT y el guard global rechazaria.
"""
import os

import pytest


@pytest.fixture
def cliente():
    import main
    main.app.config["TESTING"] = True
    with main.app.test_client() as c:
        yield c


RUTA = "/qbo/refresh_tokens_cron"


def test_sin_cron_secret_responde_503_y_no_toca_nada(cliente, monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)
    r = cliente.get(RUTA)
    assert r.status_code == 503, r.data
    assert "CRON_SECRET" in r.get_json()["detail"]


def test_sin_authorization_responde_401(cliente, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "secreto-de-prueba")
    r = cliente.get(RUTA)
    assert r.status_code == 401


def test_con_secreto_equivocado_responde_401(cliente, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "secreto-de-prueba")
    r = cliente.get(RUTA, headers={"Authorization": "Bearer otro"})
    assert r.status_code == 401


def test_el_secreto_correcto_pasa_el_guard(cliente, monkeypatch):
    """No comprueba el refresco en si (necesitaria Intuit), solo que ni el guard
    global ni el RBAC de blueprint lo rechazan: sin la exencion daria 401/403."""
    monkeypatch.setenv("CRON_SECRET", "secreto-de-prueba")
    r = cliente.get(RUTA, headers={"Authorization": "Bearer secreto-de-prueba"})
    assert r.status_code in (200, 207), r.data


def test_el_post_manual_sigue_exigiendo_jwt(cliente, monkeypatch):
    """La ruta POST de siempre NO queda exenta por añadir el cron."""
    monkeypatch.setenv("CRON_SECRET", "secreto-de-prueba")
    r = cliente.post("/qbo/refresh_tokens",
                     headers={"Authorization": "Bearer secreto-de-prueba"})
    assert r.status_code in (401, 403), r.data


def test_el_cron_esta_declarado_en_vercel_json():
    import json, pathlib
    d = json.loads((pathlib.Path(__file__).parents[2] / "vercel.json").read_text())
    rutas = [c["path"] for c in d["crons"]]
    assert RUTA in rutas, rutas
