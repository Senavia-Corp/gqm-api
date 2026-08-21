import requests
from typing import Optional
from src.podio.podio_auth import get_podio_headers
from src.utils.middleware.retries.retries import retry_api


@retry_api(max_retries=3, backoff=2)
def get_podio_item(item_id: int, app_type: str = "QID", year: Optional[int] = None) -> dict:
    """
    Trae un item completo desde Podio usando su item_id.
    app_type se usa para obtener los headers correctos.
    """
    url = f"https://api.podio.com/item/{item_id}"
    headers = get_podio_headers(app_type, year=year)

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        item_data = response.json()
        contexto = f"{app_type}_{year}" if year else app_type
        print(
            f"📦 Item obtenido correctamente desde Podio (ID: {item_id} | Contexto: {contexto}))")
        return item_data

    except requests.exceptions.HTTPError as e:
        print(f"❌ Error HTTP al obtener item {item_id}: {e} - {response.text}")
        raise

    except requests.exceptions.ConnectionError:
        print("⚠️ Error de conexión con la API de Podio.")
        raise

    except requests.exceptions.Timeout:
        print("⏰ Timeout al conectar con Podio.")
        raise

    except Exception as e:
        print(f"❌ Error inesperado al obtener item {item_id}: {e}")
        raise


def item_de_confianza(data: dict, item_id: int, app_type: str = "QID",
                      year: Optional[int] = None) -> dict:
    """El item con el que se va a ESCRIBIR en la BD, tomado de una fuente fiable.

    `data["item"]` viene del CUERPO de la petición. Podio **no manda el item**
    en sus webhooks — su payload lleva `type`, `item_id`, `item_revision_id` y
    `hook_id`, nada más — así que en producción esa rama sólo puede activarla
    alguien que la ponga a mano.

    Y hasta que `PODIO_WEBHOOK_TOKEN` esté configurada el endpoint acepta **sin
    autenticar** (medido el 20-ago-2026: `POST /webhook/podio/jobs/QID/2026` sin
    token devuelve 200, no 403; ningún hook de producción lleva token en la
    ruta). La combinación permitía sobrescribir cualquier job —campos de dinero
    incluidos— desde fuera.

    Ahora el item se lee SIEMPRE de Podio, que es la fuente de verdad. El
    `data["item"]` sólo se honra con `APP_ENV=test`, porque el arnés de
    integración inyecta los payloads por ahí (`tests/integration/
    test_webhook_jobs.py` y 4 ficheros más) y no tiene un Podio contra el que
    hablar.

    Coste en producción: una llamada a Podio por evento, que es exactamente lo
    que ya se hacía cuando el payload no traía `item` — es decir, siempre.
    """
    import os

    if os.getenv("APP_ENV") == "test":
        item = data.get("item") if isinstance(data, dict) else None
        if item:
            return item
    return get_podio_item(item_id, app_type, year=year)
