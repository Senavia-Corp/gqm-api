"""Contrato de la compuerta de aislamiento (`src/utils/db_guard.py`).

Esta tabla ES el criterio de revisión del cambio: dice exactamente qué DSN se
aceptan y cuáles no. `classify_database_url` es pura, así que estos tests no
tocan la BD ni necesitan fixtures.

Contexto: la comprobación anterior era `"ep-sparkling-sound" in DATABASE_URL`
repetida en seis ficheros. Se amplió para admitir loopback —necesario para
auditar sin acceso a Neon— y, de paso, se endureció: ahora se parsea el host en
vez de buscar una subcadena en el DSN entero.
"""
import pytest

from src.utils.db_guard import classify_database_url, require_dev_database

DEVELOP = "postgresql://u:p@ep-sparkling-sound-a1.us-east-2.aws.neon.tech/neondb"
LOOPBACK = "postgresql://gqm:pw@127.0.0.1:5432/gqm_audit"


@pytest.mark.parametrize("dsn,esperado,motivo", [
    (DEVELOP, "develop", "host de Neon develop"),
    ("postgresql://u:p@ep-pooler-x.us-east-2.aws.neon.tech/neondb"
     "?options=endpoint%3Dep-sparkling-sound-123", "develop",
     "Neon identifica el endpoint en ?options con drivers sin SNI (psycopg2)"),
    (LOOPBACK, "loopback", "loopback IPv4"),
    ("postgresql://gqm:pw@localhost:5432/db", "loopback", "loopback por nombre"),
    ("postgresql://gqm:pw@[::1]:5432/db", "loopback", "loopback IPv6"),

    ("postgresql://u:p@ep-morning-credit.us-east-2.aws.neon.tech/gqm", "rechazado",
     "PRODUCCIÓN — el rechazo que nunca debe romperse"),
    ("postgresql://u:p@ep-sparkling-sound.atacante.example/db", "rechazado",
     "se parece a develop pero no es neon.tech"),
    ("postgresql://u:p@host-de-produccion/ep-sparkling-sound", "rechazado",
     "marcador en el NOMBRE DE LA BD: la comprobación vieja lo aceptaba"),
    ("postgresql://u:p@127.0.0.1/db?host=prod.neon.tech", "rechazado",
     "libpq da prioridad a ?host=; loopback en la autoridad no basta"),
    ("postgresql://u:p@prod.example.com/db?opt=127.0.0.1", "rechazado",
     "127.0.0.1 en la query no hace local al destino"),
    ("postgresql://u:127.0.0.1@prod.example.com/db", "rechazado",
     "loopback en la CONTRASEÑA"),
    ("postgresql://u:p@localhost.atacante.tld/db", "rechazado", "sufijo engañoso"),
    ("postgresql://u:p@10.0.0.5/db", "rechazado", "LAN privada"),
    ("postgresql:///db", "rechazado", "sin host explícito: ambiguo, no pasa"),
    ("", "rechazado", "vacío"),
    ("   ", "rechazado", "solo espacios"),
])
def test_clasificacion(dsn, esperado, motivo):
    assert classify_database_url(dsn) == esperado, motivo


@pytest.mark.parametrize("dsn", [DEVELOP, LOOPBACK])
def test_app_env_sigue_siendo_obligatorio_en_ambas_ramas(dsn):
    """Ampliar a loopback no relajó APP_ENV: se exige en develop y en loopback."""
    cfg = {"DATABASE_URL": dsn, "APP_ENV": "production"}.get
    with pytest.raises(SystemExit):
        require_dev_database(lambda k, default="": cfg(k, default))


@pytest.mark.parametrize("dsn", [DEVELOP, LOOPBACK])
def test_destinos_admitidos_pasan_con_app_env_test(dsn):
    cfg = {"DATABASE_URL": dsn, "APP_ENV": "test"}.get
    assert require_dev_database(lambda k, default="": cfg(k, default)) in ("develop", "loopback")


def test_produccion_aborta_aunque_app_env_sea_test():
    cfg = {"DATABASE_URL": "postgresql://u:p@ep-morning-credit.aws.neon.tech/gqm",
           "APP_ENV": "test"}.get
    with pytest.raises(SystemExit):
        require_dev_database(lambda k, default="": cfg(k, default))
