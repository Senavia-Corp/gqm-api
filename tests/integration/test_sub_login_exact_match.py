"""REG-036/REG-050: el login de subcontratista matchea por igualdad exacta."""
import uuid

from decouple import config
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.models.SubcontractorModel import Subcontractor


def test_substring_email_cannot_login_as_superset(client):
    """Antes: .contains → 'dev@senavia-test.com' resolvía a
    'sub-dev@senavia-test.com' y bastaba conocer SU contraseña."""
    password = config("SEED_DEV_PASSWORD")
    resp = client.post("/auth/login", json={
        "Email_Address": "dev@senavia-test.com",  # substring del email real
        "Password": password,
    })
    assert resp.status_code in (401, 404), resp.get_data(as_text=True)[:200]


def test_exact_email_logs_in_case_insensitive(client):
    resp = client.post("/auth/login", json={
        "Email_Address": "SUB-DEV@senavia-test.com",
        "Password": config("SEED_DEV_PASSWORD"),
    })
    assert resp.status_code == 200
    assert resp.get_json()["user_type"] == "subcontractor"
