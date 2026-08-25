from src.utils.middleware.logs.logs import logger
import requests
from src.podio.podio_auth import get_podio_headers
from src.config import (
    APP_ENV,
    BASE_URL,
    PODIO_READONLY,
    PODIO_STRICT_APP_MATCH,
    app_ids_configurados,
)
from src.utils.mappers.clean_podio_fields import clean_podio_fields
from src.utils.middleware.retries.retries import retry_api, retry_api_lectura


class EscrituraFueraDeEntorno(Exception):
    """Se intentó escribir en un item de Podio que no pertenece a este entorno."""


# ---- Inventario de campos por (tipo, año), generado desde el esquema real ----
#
# Las apps NO son iguales entre años: QID 2023 tiene 293 campos y 2026 tiene 255.
# En concreto, **QID 2023 y 2024 no tienen `bldg-fees-*`** ni
# `expected-completioninvoice`, y PAR 2023 no tiene `par-pricing-target`.
#
# Podio rechaza la actualización ENTERA con `field.not.found` cuando el payload
# trae un campo que la app no tiene — no ignora el que sobra. Así que mandar el
# mapa de 2026 a un job de 2023 no fallaba «un poco»: fallaba del todo, y ese
# job no sincronizaba nada.
_INVENTARIO_CAMPOS = None


def _campos_de_la_app(app_type, year):
    """Los `external_id` que existen en esa app-año, o None si no se sabe."""
    global _INVENTARIO_CAMPOS
    if _INVENTARIO_CAMPOS is None:
        import json
        import pathlib
        try:
            ruta = pathlib.Path(__file__).resolve().parents[1] / "campos_por_anio.json"
            _INVENTARIO_CAMPOS = json.loads(ruta.read_text())["apps"]
        except Exception:
            logger.warning("Sin inventario de campos por año: no se filtrará el payload")
            _INVENTARIO_CAMPOS = {}
    anios = _INVENTARIO_CAMPOS.get((app_type or "").upper())
    if not anios or year is None:
        return None
    campos = anios.get(str(year))
    return set(campos) if campos else None


class EscrituraPodioBloqueada(EscrituraFueraDeEntorno):
    """La escritura estaba prohibida por bandera, no por pertenecer a otra app.

    Subclase a propósito: los `except EscrituraFueraDeEntorno` que ya existen la
    siguen atrapando.
    """


class PodioBaseService:

    # Servicio genérico para interactuar con cualquier App de Podio.
    def __init__(self, app_type: str, app_id: str, year: int | None = None):
        self.app_type = app_type
        self.app_id = app_id
        self.year = year

    def _filtrar_por_anio(self, fields: dict, operacion: str) -> dict:
        """Quita del payload los campos que esa app-año no tiene.

        Es preferible sincronizar de menos que no sincronizar nada: Podio
        rechaza la actualización entera si un solo campo no existe.
        """
        existentes = _campos_de_la_app(self.app_type, self.year)
        if not existentes:
            return fields
        sobran = [k for k in fields if k not in existentes]
        if sobran:
            logger.warning(
                "%s en %s %s: %d campos no existen en esa app y no se mandan: %s",
                operacion, self.app_type, self.year, len(sobran), sorted(sobran))
        return {k: v for k, v in fields.items() if k in existentes}

    def _headers(self):
        if self.year is not None:
            return get_podio_headers(self.app_type, self.year)

        return get_podio_headers(self.app_type)

    # ------------- PORTAL ÚNICO DE ESCRITURA (A-9) -------------

    def _verificar_escritura_permitida(self, operacion: str, item_id=None):
        """El único punto por el que salen las escrituras a Podio.

        Antes esto era `_exigir_app_permitida` y lo llamaban solo `update_item` y
        `delete_item`: **`create_item` no llamaba a nada**, así que la guarda no
        cubría el camino que crea items.

        Contexto (A-9, 10-ago-2026): la BD de develop está llena de
        `podio_item_id` de PRODUCCIÓN — 97 de 100 clientes y 22 de 57 communities
        apuntan a la app real `22192695`. Las apps TEST comparten el espacio de
        Podio 6405055 con las reales, así que el token de prueba **alcanza
        producción** (lectura comprobada, HTTP 200). Un solo
        `PATCH /clients/<id>?sync_podio=true` desde dev escribía sobre la ficha
        real del cliente, y `verificar-aislamiento.sh` no lo veía: solo mira el
        `.env`.

        Tres guardas, de la más barata a la más cara:

        1. `PODIO_READONLY` — corta todo, en cualquier entorno.
        2. La app del **servicio** está en la lista blanca. Sin red, y es la
           única que puede proteger a `create_item`, donde todavía no hay item
           que resolver.
        3. Solo con `item_id` y solo si `PODIO_STRICT_APP_MATCH`: se resuelve a
           qué app pertenece el item de verdad y se exige (a) que esté en la
           lista blanca y (b) que sea **exactamente** la del servicio. (b) es lo
           único que atrapa un borrado apuntando al año equivocado.

        En producción, con las banderas apagadas, el coste es cero: la guarda 2
        siempre pasa (todo servicio se construye desde la misma config que
        alimenta la lista) y la 3 no llega a hacer el GET.
        """
        if PODIO_READONLY:
            raise EscrituraPodioBloqueada(
                f"{operacion} bloqueado: PODIO_READONLY está activo. Las escrituras "
                f"salientes a Podio están pausadas (ventana de reconciliación). "
                f"Las entregas entrantes de webhook siguen guardándose en la BD."
            )

        permitidas = app_ids_configurados()
        if permitidas and str(self.app_id) not in permitidas:
            raise EscrituraFueraDeEntorno(
                f"{operacion} BLOQUEADO: este servicio apunta a la app de Podio "
                f"{self.app_id}, que no está configurada en este entorno "
                f"(APP_ENV={APP_ENV}). Apps permitidas: {sorted(permitidas)}."
            )

        if item_id is None or not PODIO_STRICT_APP_MATCH:
            return

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

        if not app_id:
            return

        if app_id not in permitidas:
            raise EscrituraFueraDeEntorno(
                f"{operacion} del item {item_id} BLOQUEADO: pertenece a la app de Podio "
                f"{app_id}, que no está configurada en este entorno (APP_ENV={APP_ENV}). "
                f"Apps permitidas: {sorted(permitidas)}. "
                f"Casi seguro es un item de PRODUCCIÓN referenciado desde datos de dev."
            )

        if app_id != str(self.app_id):
            raise EscrituraFueraDeEntorno(
                f"{operacion} del item {item_id} BLOQUEADO: el item vive en la app "
                f"{app_id} pero este servicio escribe en la {self.app_id}. "
                f"Casi seguro es el año equivocado: el item se resolvió con un "
                f"`podio_app_year` que no es el suyo."
            )

    def _exigir_app_permitida(self, item_id, operacion: str):
        """Nombre anterior de la guarda. Se conserva: hay tests que lo llaman."""
        return self._verificar_escritura_permitida(operacion, item_id=item_id)

    # ------------- GET ITEMS -------------

    @retry_api_lectura()
    def get_items_page(self, limit: int = 50, offset: int = 0) -> dict:
        """Una página del filtro de la app, CON los contadores que Podio devuelve.

        `filtered` = items que pasan el filtro; `total` = items de la app. Sin
        filtros son iguales, y `total` es el número que el cliente ve en la UI de
        Podio — el que tiene que cuadrar con la BD.

        `get_items` los tiraba (`.get("items", [])`), y sin ellos no hay forma de
        saber cuándo se ha terminado de paginar ni de comparar contra la BD.
        """
        url = f"{BASE_URL}/item/app/{self.app_id}/filter/"
        params = {"limit": limit, "offset": offset}

        response = requests.post(url, headers=self._headers(), json=params)
        response.raise_for_status()
        cuerpo = response.json()

        return {
            "items": cuerpo.get("items", []),
            "filtered": cuerpo.get("filtered"),
            "total": cuerpo.get("total"),
            "limit": limit,
            "offset": offset,
        }

    def get_items(self, limit=50, offset=0):
        # Firma intacta a propósito: los llamadores vivos esperan solo la lista.
        # Al delegar hereda `retry_api_lectura`, así que un 403 ahora falla al
        # instante en vez de a los 6 s. Es lo deseado: era una lectura decorada
        # con la política de reintento de las escrituras.
        return self.get_items_page(limit=limit, offset=offset)["items"]

    @retry_api(max_retries=3, backoff=2)
    def get_item(self, item_id: int):

        url = f"{BASE_URL}/item/{item_id}"
        response = requests.get(url, headers=self._headers())
        response.raise_for_status()

        return response.json()

    # ------------- CREATE -------------

    @retry_api(max_retries=3, backoff=2)
    def create_item(self, fields: dict):

        self._verificar_escritura_permitida("CREATE")

        url = f"{BASE_URL}/item/app/{self.app_id}/"

        fields = self._filtrar_por_anio(fields, "CREATE")
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

        self._verificar_escritura_permitida("UPDATE", item_id=item_id)

        url = f"{BASE_URL}/item/{item_id}"

        fields = self._filtrar_por_anio(fields, "UPDATE")
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

        self._verificar_escritura_permitida("DELETE", item_id=item_id)

        url = f"{BASE_URL}/item/{item_id}"
        response = requests.delete(url, headers=self._headers())

        if response.status_code in [200, 202, 204]:
            return True

        response.raise_for_status()
        return False


class PodioReadOnlyService(PodioBaseService):
    """Idéntico para leer; cualquier escritura levanta antes de tocar la red.

    Lo usa el censo de paridad y el importador. La diferencia con confiar en
    `PODIO_READONLY` o en pasar `dry_run` es que aquí no hay nada que recordar:
    si el objeto que tienes en la mano es de esta clase, un bug de llamada no
    puede escribir en Podio ni aunque las banderas estén apagadas.
    """

    def _no(self, operacion: str):
        raise EscrituraPodioBloqueada(
            f"{operacion} bloqueado: este servicio es de SOLO LECTURA "
            f"(app {self.app_id}, tipo {self.app_type}, año {self.year})."
        )

    def create_item(self, fields: dict):
        self._no("CREATE")

    def update_item(self, item_id: int, fields: dict):
        self._no("UPDATE")

    def delete_item(self, item_id: str):
        self._no("DELETE")
