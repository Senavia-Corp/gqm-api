"""REG-002/REG-010: URLs de registro de webhooks apuntan a rutas reales."""
from urllib.parse import urlsplit

import pytest

from src.podio.webhook.func_hooks import build_webhook_target


def _path(url):
    return urlsplit(url).path


def test_jobs_target_is_year_scoped():
    assert _path(build_webhook_target("QID", 2026)) == "/webhook/podio/jobs/QID/2026"
    assert _path(build_webhook_target("par", 2024)) == "/webhook/podio/jobs/PAR/2024"


def test_jobs_without_year_raises():
    with pytest.raises(ValueError):
        build_webhook_target("QID")


def test_relation_and_no_relation_targets():
    assert _path(build_webhook_target("CLI")) == "/webhook/podio/others/relations/CLI"
    assert _path(build_webhook_target("SUBC")) == "/webhook/podio/others/relations/SUBC"
    assert _path(build_webhook_target("PMC")) == "/webhook/podio/others/no_relations/PMC"
    assert _path(build_webhook_target("BDEP")) == "/webhook/podio/others/no_relations/BDEP"


def test_unknown_app_type_raises():
    with pytest.raises(ValueError):
        build_webhook_target("TASK")


def test_target_carries_auth_token_when_configured():
    # En dev el .env define PODIO_WEBHOOK_TOKEN; la validación se activa en B2.
    url = build_webhook_target("QID", 2026)
    assert "token=" in urlsplit(url).query
