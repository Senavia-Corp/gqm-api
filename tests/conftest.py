"""Arnés de tests Fase 1.

Los tests de integración escriben en Neon develop (desechable). Las guardas
de abajo abortan la sesión completa de pytest si el .env no es el de dev.
"""
import sys

from decouple import config

if "ep-sparkling-sound" not in config("DATABASE_URL", default=""):
    sys.exit("⛔ DATABASE_URL no apunta a Neon develop — tests abortados")
if config("APP_ENV", default="") != "test":
    sys.exit("⛔ APP_ENV != test — tests abortados")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def app():
    from main import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db_session():
    from src.database.db_sqlmodel import get_session

    with get_session() as session:
        yield session


@pytest.fixture(scope="session")
def admin_headers(app):
    """JWT del admin dev sembrado por scripts/seed_rbac.py."""
    password = config("SEED_DEV_PASSWORD", default="")
    assert password, "falta SEED_DEV_PASSWORD en el .env de dev"
    resp = app.test_client().post(
        "/auth/login",
        json={"Email_Address": "admin-dev@senavia-test.com", "Password": password},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    return {"Authorization": f"Bearer {resp.get_json()['access_token']}"}
