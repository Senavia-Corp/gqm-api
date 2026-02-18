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
