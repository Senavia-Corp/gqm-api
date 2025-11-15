import requests
from src.podio.podio_auth import get_podio_headers
from src.config import PUBLIC_URL, PODIO_TAP_APP_ID


def clear_existing_webhooks():
    """Elimina todos los webhooks antiguos de la app en Podio."""
    headers = get_podio_headers()
    base_url = f"https://api.podio.com/hook/app/{PODIO_TAP_APP_ID}"

    try:
        response = requests.get(base_url, headers=headers)
        response.raise_for_status()
    except Exception as e:
        print(f"❌ No se pudo listar los webhooks: {e}")
        return

    hooks = response.json()
    if not hooks:
        print("ℹ️ No hay webhooks antiguos para borrar")
        return

    for hook in hooks:
        hook_id = hook.get("hook_id")
        if not hook_id:
            continue
        del_response = requests.delete(
            f"{base_url}/{hook_id}", headers=headers)
        if del_response.status_code == 204:
            print(f"🗑️ Webhook {hook_id} eliminado")
        elif del_response.status_code == 404:
            print(f"ℹ️ Webhook {hook_id} ya no existe")
        else:
            print(
                f"❌ Error eliminando webhook {hook_id}: {del_response.status_code}")


def register_podio_webhooks():
    """Registra los webhooks necesarios (create, update, delete)."""
    headers = get_podio_headers()
    base_url = f"https://api.podio.com/hook/app/{PODIO_TAP_APP_ID}"

    events = ["item.create", "item.update", "item.delete"]

    for event_type in events:
        payload = {
            "url": f"{PUBLIC_URL}/webhook/podio",
            "type": event_type
        }

        response = requests.post(base_url, headers=headers, json=payload)
        if response.status_code == 200:
            print(f"✅ Webhook '{event_type}' registrado exitosamente")
        elif response.status_code == 409:
            print(f"ℹ️ Webhook '{event_type}' ya estaba registrado")
        else:
            print(
                f"❌ Error registrando '{event_type}': {response.status_code} {response.text}")
