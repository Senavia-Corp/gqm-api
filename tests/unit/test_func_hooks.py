"""REG-002/REG-010: URLs de registro de webhooks apuntan a rutas reales.

REG-018 (revisado el 10-ago-2026): el token de autenticación va en la RUTA, no
en el query string. Podio DESCARTA el query al entregar sus eventos —medido en
los logs de gqm-api-dev, la ruta se conserva y el `?token=` no llega—, así que
con el token en el query NINGÚN hook podía entregar nada y todo respondía 403.
Estos tests afirmaban la forma antigua: codificaban el comportamiento roto.
"""
from urllib.parse import urlsplit

import pytest
from decouple import config as env_config

from src.podio.webhook.func_hooks import build_webhook_target, redact_hook_url

TOKEN = env_config("PODIO_WEBHOOK_TOKEN", default="")


def _path(url):
    return urlsplit(url).path


def _path_sin_token(url):
    """La ruta sin el segmento final del token, para comparar la parte estable."""
    p = _path(url)
    if TOKEN and p.endswith("/" + TOKEN):
        return p[: -len(TOKEN) - 1]
    return p


def test_jobs_target_is_year_scoped():
    assert _path_sin_token(build_webhook_target("QID", 2026)) == "/webhook/podio/jobs/QID/2026"
    assert _path_sin_token(build_webhook_target("par", 2024)) == "/webhook/podio/jobs/PAR/2024"


def test_jobs_without_year_raises():
    with pytest.raises(ValueError):
        build_webhook_target("QID")


def test_relation_and_no_relation_targets():
    assert _path_sin_token(build_webhook_target("CLI")) == "/webhook/podio/others/relations/CLI"
    assert _path_sin_token(build_webhook_target("SUBC")) == "/webhook/podio/others/relations/SUBC"
    assert _path_sin_token(build_webhook_target("PMC")) == "/webhook/podio/others/no_relations/PMC"
    assert _path_sin_token(build_webhook_target("BDEP")) == "/webhook/podio/others/no_relations/BDEP"


def test_unknown_app_type_raises():
    with pytest.raises(ValueError):
        build_webhook_target("NOPE")


@pytest.mark.skipif(not TOKEN, reason="requiere PODIO_WEBHOOK_TOKEN configurado")
def test_el_token_va_en_la_ruta_no_en_el_query():
    url = build_webhook_target("QID", 2026)
    assert urlsplit(url).query == "", "el token NO debe ir en el query: Podio lo descarta"
    assert _path(url).endswith("/" + TOKEN), "el token debe ser el último segmento de la ruta"


@pytest.mark.skipif(not TOKEN, reason="requiere PODIO_WEBHOOK_TOKEN configurado")
def test_el_prefijo_publico_se_mantiene():
    """main.py whitelista los receptores por PREFIJO: si el token se colara antes
    de /jobs, el middleware global responderia 401 y no llegaria nada."""
    for url in (build_webhook_target("QID", 2026), build_webhook_target("CLI")):
        p = _path(url)
        assert p.startswith("/webhook/podio/jobs") or p.startswith("/webhook/podio/others")


@pytest.mark.skipif(not TOKEN, reason="requiere PODIO_WEBHOOK_TOKEN configurado")
def test_la_redaccion_oculta_el_token_de_la_ruta():
    """redact_hook_url solo tapaba `token=`; el secreto salia por los logs y por
    la respuesta de /admin/webhooks/<app>/register."""
    url = build_webhook_target("QID", 2026)
    assert TOKEN not in redact_hook_url(url)
