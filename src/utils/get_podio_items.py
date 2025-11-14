import requests
from src.podio.podio_auth import get_podio_headers


def get_podio_item(item_id: int) -> dict:

    url = f"https://api.podio.com/item/{item_id}"
    headers = get_podio_headers()

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        item_data = response.json()
        print(f"📦 Item obtenido correctamente desde Podio (ID: {item_id})")
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
