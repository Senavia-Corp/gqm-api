"""Compuerta de aislamiento: a qué base de datos se permite apuntar.

Origen: hasta ahora cada arnés repetía la misma línea

    if "ep-sparkling-sound" not in config("DATABASE_URL", default=""): sys.exit(...)

en `tests/conftest.py`, `scripts/seed_rbac.py`, `scripts/cleanup_rbac.py` y
`scripts/audit_tasks_matrix.py`. Eso es una allowlist por subcadena de hostname,
no una propiedad de seguridad, y tiene dos defectos:

1. Rechaza un Postgres en **loopback**, que es estrictamente más seguro que Neon
   develop: no tiene ruta de red hacia ningún sitio, y menos hacia producción.
2. Una subcadena se deja engañar. La comprobación vieja miraba el DSN ENTERO,
   así que `postgresql://u:p@host-de-produccion/ep-sparkling-sound` pasaba: el
   marcador estaba en el nombre de la base de datos, no en el host. Y al añadir
   la rama de loopback aparece el simétrico —`...@prod.neon.tech/db?opt=127.0.0.1`
   contiene "127.0.0.1" sin ser local—, que este módulo evita parseando.

Este módulo centraliza la decisión y **parsea el host de verdad**. No relaja nada:
sigue exigiendo `APP_ENV=test` y sigue rechazando cualquier host que no sea ni el
de develop ni loopback. Lo único que añade es la rama de loopback.

`scripts/rbac_spec_produccion.py` NO usa este módulo a propósito: ese script exige
un host de producción, que es justo lo contrario.
"""
import sys
from urllib.parse import parse_qs, urlparse

# Host de Neon develop (desechable). Se conserva tal cual estaba.
DEVELOP_HOST_MARKER = "ep-sparkling-sound"

# Únicos hosts locales admitidos. `localhost` incluido porque libpq lo resuelve
# a loopback; cualquier otro nombre queda fuera aunque resuelva a 127.0.0.1,
# porque la resolución puede cambiar y no es comprobable aquí.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "[::1]", "localhost"})


def _hosts_in(dsn: str) -> list[str]:
    """Todos los hosts que libpq podría usar: el de la autoridad y los de la
    query (`?host=`/`?hostaddr=`, que tienen prioridad sobre la autoridad)."""
    parsed = urlparse(dsn)
    hosts = []
    if parsed.hostname:
        hosts.append(parsed.hostname)
    query = parse_qs(parsed.query)
    for key in ("host", "hostaddr"):
        for value in query.get(key, []):
            hosts.extend(v for v in value.split(",") if v)
    return [h.strip().lower() for h in hosts if h.strip()]


def _es_develop(dsn: str, hosts: list[str]) -> bool:
    """¿Apunta a Neon develop?

    El marcador puede venir en el host (`ep-sparkling-sound-x.neon.tech`) o en
    `?options=endpoint%3Dep-sparkling-sound-x`, que es como Neon identifica el
    endpoint con drivers sin SNI — psycopg2 entre ellos. Mirar solo el host
    habría RECHAZADO ese segundo DSN, que la comprobación por subcadena
    original sí aceptaba: sería una regresión, no un endurecimiento.

    Se exige además que el destino sea de neon.tech, para que un
    `ep-sparkling-sound.atacante.example` no se cuele por parecerse.
    """
    if any(DEVELOP_HOST_MARKER in h and h.endswith(".neon.tech") for h in hosts):
        return True
    opciones = parse_qs(urlparse(dsn).query).get("options", [])
    return (any(h.endswith(".neon.tech") for h in hosts)
            and any(DEVELOP_HOST_MARKER in o for o in opciones))


def classify_database_url(dsn: str) -> str:
    """`develop` | `loopback` | `rechazado`. Función pura: sin efectos, testeable.

    Un DSN es `loopback` solo si **todos** sus hosts lo son. Basta un host
    remoto para rechazarlo: no se admite una mezcla.
    """
    if not dsn or not dsn.strip():
        return "rechazado"
    hosts = _hosts_in(dsn)
    if not hosts:
        # Sin host explícito libpq usaría el socket unix local, pero preferimos
        # exigirlo escrito: un DSN ambiguo no pasa.
        return "rechazado"
    if all(h in LOOPBACK_HOSTS for h in hosts):
        return "loopback"
    if _es_develop(dsn, hosts):
        return "develop"
    return "rechazado"


def require_dev_database(config, *, contexto: str = "") -> str:
    """Aborta salvo que el destino sea develop o loopback, y `APP_ENV=test`.

    `config` es el `decouple.config` del llamante (así el módulo no impone de
    dónde se leen las variables). Devuelve la clasificación para que el llamante
    pueda registrarla. Aborta con `sys.exit`, igual que antes.
    """
    sufijo = f" ({contexto})" if contexto else ""
    dsn = config("DATABASE_URL", default="")
    destino = classify_database_url(dsn)
    if destino == "rechazado":
        sys.exit(
            f"⛔ DATABASE_URL no es ni Neon develop ni loopback — abortado{sufijo}.\n"
            f"   Admitidos: host con «{DEVELOP_HOST_MARKER}», o {sorted(LOOPBACK_HOSTS)}."
        )
    if config("APP_ENV", default="") != "test":
        sys.exit(f"⛔ APP_ENV != test — abortado{sufijo}")
    return destino
