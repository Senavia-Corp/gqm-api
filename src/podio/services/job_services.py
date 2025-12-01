import requests
from src.podio.podio_auth import get_podio_headers
from src.config import PODIO_TAP_APP_ID, BASE_URL
from src.utils.clean_podio_fields import clean_podio_fields
from src.utils.middleware.retries.retries import retry_api


# ============================================================
# Integración con Podio (Test Admin Panel)

def podio_headers():
    # Obtiene los headers de autorización para Podio.
    return get_podio_headers()


# ------------------ GET ------------------
@retry_api(max_retries=3, backoff=2)
def get_podio_jobs(limit=50, offset=0):

    headers = podio_headers()
    url = f"{BASE_URL}/item/app/{PODIO_TAP_APP_ID}/filter/"
    params = {"limit": limit, "offset": offset}

    response = requests.post(url, headers=headers, json=params)
    response.raise_for_status()

    return response.json().get("items", [])


# ------------------ CREATE ------------------
@retry_api(max_retries=3, backoff=2)
def create_podio_job(fields: dict):
    headers = podio_headers()
    url = f"{BASE_URL}/item/app/{PODIO_TAP_APP_ID}/"

    # Limpieza y conversión
    podio_ready_fields = clean_podio_fields(fields)

    print(f"📤 Enviando a Podio (limpio): {podio_ready_fields}")

    payload = {"fields": podio_ready_fields}
    response = requests.post(url, headers=headers, json=payload)

    try:

        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print("⚠️ Error al crear item en Podio:")
        print(response.text)
        raise

    return response.json()


# ------------------ UPDATE ------------------
@retry_api(max_retries=3, backoff=2)
def update_podio_job(item_id: int, fields: dict):
    headers = podio_headers()
    url = f"{BASE_URL}/item/{item_id}"

    # Limpieza y conversión
    podio_ready_fields = clean_podio_fields(fields)
    print(
        f"🧩 Actualizando item {item_id} en Podio (limpio): {podio_ready_fields}")

    payload = {"fields": podio_ready_fields}

    try:
        response = requests.put(url, headers=headers, json=payload)
        response.raise_for_status()
        print(f"✅ Item {item_id} actualizado correctamente en Podio")

    except requests.exceptions.HTTPError as e:
        print("⚠️ Error al actualizar item en Podio:")
        print(response.text)
        raise

    # --- 🔥 SIMPLE FIX: Podio a veces no devuelve JSON ---
    if not response.text.strip():
        return {"status": "ok", "item_id": item_id}

    try:
        return response.json()
    except ValueError:
        return {"status": "ok", "item_id": item_id}


# ------------------ DELETE ------------------
@retry_api(max_retries=3, backoff=2)
def delete_podio_job(item_id: str):

    headers = podio_headers()
    url = f"{BASE_URL}/item/{item_id}/"
    response = requests.delete(url, headers=headers)

    if response.status_code in [200, 202, 204]:
        return True
    else:
        response.raise_for_status()
        return False
