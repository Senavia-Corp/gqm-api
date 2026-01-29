import requests
from src.podio.podio_auth import get_podio_headers
from src.config import BASE_URL
from src.utils.mappers.clean_podio_fields import clean_podio_fields
from src.utils.middleware.retries.retries import retry_api


class PodioBaseService:

    # Servicio genérico para interactuar con cualquier App de Podio.
    def __init__(self, app_type: str, app_id: str):
        self.app_type = app_type    # QID, CLI, PMC, etc..
        self.app_id = app_id        # ID numérica del App en Podio

    def _headers(self):
        return get_podio_headers(self.app_type)

    # ------------- GET ITEMS -------------
    @retry_api(max_retries=3, backoff=2)
    def get_items(self, limit=50, offset=0):

        url = f"{BASE_URL}/item/app/{self.app_id}/filter/"
        params = {"limit": limit, "offset": offset}

        response = requests.post(url, headers=self._headers(), json=params)
        response.raise_for_status()

        return response.json().get("items", [])

    @retry_api(max_retries=3, backoff=2)
    def get_item(self, item_id: int):

        url = f"{BASE_URL}/item/{item_id}"
        response = requests.get(url, headers=self._headers())
        response.raise_for_status()

        return response.json()

    # ------------- CREATE -------------

    @retry_api(max_retries=3, backoff=2)
    def create_item(self, fields: dict):

        url = f"{BASE_URL}/item/app/{self.app_id}/"

        podio_fields = clean_podio_fields(fields)  # Limpieza y conversión
        print(f"📤 Enviando a Podio (limpio): {podio_fields}")

        payload = {"fields": podio_fields}
        response = requests.post(url, headers=self._headers(), json=payload)

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            print("⚠️ Error al crear item en Podio:")
            print(response.text)
            raise

        return response.json()

    # ------------- UPDATE -------------

    @retry_api(max_retries=3, backoff=2)
    def update_item(self, item_id: int, fields: dict):

        url = f"{BASE_URL}/item/{item_id}"

        podio_fields = clean_podio_fields(fields)
        print(
            f"🧩 Actualizando item {item_id} en Podio (limpio): {podio_fields}")

        payload = {"fields": podio_fields}

        try:
            response = requests.put(url, headers=self._headers(), json=payload)
            response.raise_for_status()
            print(f"✅ Item {item_id} actualizado correctamente en Podio")

        except requests.exceptions.HTTPError:
            print("⚠️ Error al actualizar item en Podio:")
            print(response.text)
            raise

        if not response.text.strip():
            return {"status": "ok", "item_id": item_id}

        try:
            return response.json()
        except ValueError:
            return {"status": "ok", "item_id": item_id}

    # ------------- DELETE -------------
    @retry_api(max_retries=3, backoff=2)
    def delete_item(self, item_id: str):

        url = f"{BASE_URL}/item/{item_id}"
        response = requests.delete(url, headers=self._headers())

        if response.status_code in [200, 202, 204]:
            return True

        response.raise_for_status()
        return False
