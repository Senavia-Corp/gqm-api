import requests
from src.podio.podio_auth import get_podio_headers
from src.config import PUBLIC_URL, get_podio_app_credentials
from src.utils.middleware.retries.retries import retry_api


def get_app_id(app_type: str):
    creds = get_podio_app_credentials(app_type)
    return creds["APP_ID"]


@retry_api(max_retries=3, backoff=2)
def list_webhooks(app_type: str):
    """
    Lista los webhooks del app indicado.
    """
    headers = get_podio_headers(app_type)
    app_id = get_app_id(app_type)

    url = f"https://api.podio.com/hook/app/{app_id}/"
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


@retry_api(max_retries=3, backoff=2)
def clear_existing_webhooks(app_type: str):
    """
    Elimina todos los webhooks de la app indicada.
    """
    headers = get_podio_headers(app_type)

    try:
        hooks = list_webhooks(app_type)
    except Exception as e:
        print(f"❌ No se pudo listar webhooks: {e}")
        return False, str(e)

    if not hooks:
        print("ℹ️ No hay webhooks para borrar")
        return True, "No hooks"

    errors = []
    for hook in hooks:
        hook_id = hook.get("hook_id") or hook.get("hookId") or hook.get("id")
        if not hook_id:
            continue

        delete_url = f"https://api.podio.com/hook/{hook_id}"
        del_resp = requests.delete(delete_url, headers=headers)

        if del_resp.status_code in (200, 202, 204):
            print(f"🗑️ Webhook {hook_id} eliminado")
        elif del_resp.status_code == 404:
            print(f"ℹ️ Webhook {hook_id} ya no existe")
        else:
            err = f"Error eliminando {hook_id}: {del_resp.status_code} {del_resp.text}"
            print("❌", err)
            errors.append(err)

    return (len(errors) == 0), errors


@retry_api(max_retries=3, backoff=2)
def register_podio_webhooks(app_type: str):
    """
    Registra webhooks create, update y delete para la app indicada.
    """
    headers = get_podio_headers(app_type)
    app_id = get_app_id(app_type)

    base_url = f"https://api.podio.com/hook/app/{app_id}"

    target = f"{PUBLIC_URL}/webhook/podio/{app_type.lower()}"

    events = ["item.create", "item.update", "item.delete"]
    results = {"created": [], "skipped": [], "errors": []}

    for ev in events:
        payload = {"url": target, "type": ev}
        resp = requests.post(base_url, headers=headers, json=payload)

        if resp.status_code == 200:
            print(f"✅ Webhook '{ev}' registrado en {app_type}")
            results["created"].append(resp.json())
        elif resp.status_code == 409:
            print(f"ℹ️ Webhook '{ev}' ya existía en {app_type}")
            results["skipped"].append(ev)
        else:
            err = {"event": ev, "status": resp.status_code, "text": resp.text}
            print("❌ Error registrando webhook:", err)
            results["errors"].append(err)

    return results
