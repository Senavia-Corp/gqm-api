from src.utils.middleware.logs.logs import logger
import requests
from src.podio.podio_auth import get_podio_headers
from src.config import APP_ENV, BASE_URL, app_ids_configurados
from src.utils.mappers.clean_podio_fields import clean_podio_fields
from src.utils.middleware.retries.retries import retry_api


class EscrituraFueraDeEntorno(Exception):
    """Se intentó escribir en un item de Podio que no pertenece a este entorno."""


class PodioBaseService:

    # Servicio genérico para interactuar con cualquier App de Podio.
    def __init__(self, app_type: str, app_id: str, year: int | None = None):
        self.app_type = app_type
        self.app_id = app_id
        self.year = year

    def _headers(self):
        if self.year is not None:
            return get_podio_headers(self.app_type, self.year)

        return get_podio_headers(self.app_type)

    # ------------- GUARDA DE ENTORNO (A-9) -------------

    def _exigir_app_permitida(self, item_id, operacion: str):
        """Impide escribir en items que no son de este entorno.

        El 10-ago-2026 se descubrió que la BD de develop está llena de
        `podio_item_id` de PRODUCCIÓN: 97 de 100 clientes y 22 de 57 communities
        apuntan a la app real `22192695`. Y las apps TEST comparten el espacio de
        Podio 6405055 con las reales, así que el token de prueba **alcanza
        producción** (lectura comprobada con HTTP 200).

        Con eso, un solo `PATCH /clients/<id>?sync_podio=true` desde desarrollo
        escribía sobre la ficha real del cliente. La compuerta
        `verificar-aislamiento.sh` no lo veía: solo mira el `.env`.

        Aquí se corta en el único sitio por el que salen todas las escrituras:
        se resuelve a qué app pertenece el item y se exige que esté entre las
        que esta configuración puede tocar (en `APP_ENV=test`, las TAP).

        Cuesta un GET extra por escritura y SOLO en test: en producción la
        lista blanca son las apps reales y no hay nada que impedir, así que se
        sale sin llamar a Podio.
        """
        if APP_ENV != "test":
            return

        permitidas = app_ids_configurados()
        try:
            resp = requests.get(
                f"{BASE_URL}/item/{item_id}/basic", headers=self._headers(), timeout=30)
            resp.raise_for_status()
            app_id = str((resp.json().get("app") or {}).get("app_id") or "")
        except requests.exceptions.RequestException as e:
            # Fail-closed a propósito: si no se puede comprobar de qué entorno es
            # el item, NO se escribe. Perder una sincronización en dev es
            # barato; escribir en producción no.
            raise EscrituraFueraDeEntorno(
                f"{operacion} del item {item_id} bloqueado: no se pudo verificar a qué "
                f"app de Podio pertenece ({e})") from e

        if app_id and app_id not in permitidas:
            raise EscrituraFueraDeEntorno(
                f"{operacion} del item {item_id} BLOQUEADO: pertenece a la app de Podio "
                f"{app_id}, que no está configurada en este entorno (APP_ENV={APP_ENV}). "
                f"Apps permitidas: {sorted(permitidas)}. "
                f"Casi seguro es un item de PRODUCCIÓN referenciado desde datos de dev."
            )

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
        except requests.exceptions.HTTPError as e:
            logger.error("PODIO API ERROR on create_item! Payload was: %s", podio_fields)
            print("⚠️ Error al crear item en Podio:")
            print(response.text)
            raise

        return response.json()

    # ------------- UPDATE -------------

    @retry_api(max_retries=3, backoff=2)
    def update_item(self, item_id: int, fields: dict):

        self._exigir_app_permitida(item_id, "UPDATE")

        url = f"{BASE_URL}/item/{item_id}"

        podio_fields = clean_podio_fields(fields)
        print(
            f"🧩 Actualizando item {item_id} en Podio (limpio): {podio_fields}")

        payload = {"fields": podio_fields}

        try:
            response = requests.put(url, headers=self._headers(), json=payload)
            response.raise_for_status()
            print(f"✅ Item {item_id} actualizado correctamente en Podio")

        except requests.exceptions.HTTPError as e:
            error_details = e.response.text
            logger.error("PODIO API ERROR on update_item! Payload was: %s", payload)
            print("⚠️ Error al actualizar item en Podio:")
            print(error_details)
            # Levantar una excepción con el detalle exacto de Podio
            raise Exception(f"Podio Update Error {e.response.status_code}: {error_details}") from e

        if not response.text.strip():
            return {"status": "ok", "item_id": item_id}

        try:
            return response.json()
        except ValueError:
            return {"status": "ok", "item_id": item_id}

    # ------------- DELETE -------------
    @retry_api(max_retries=3, backoff=2)
    def delete_item(self, item_id: str):

        self._exigir_app_permitida(item_id, "DELETE")

        url = f"{BASE_URL}/item/{item_id}"
        response = requests.delete(url, headers=self._headers())

        if response.status_code in [200, 202, 204]:
            return True

        response.raise_for_status()
        return False
