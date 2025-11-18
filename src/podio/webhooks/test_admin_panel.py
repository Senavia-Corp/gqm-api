import requests
from src.podio.podio_auth import get_podio_headers
from src.config import PUBLIC_URL, PODIO_TAP_APP_ID


def list_webhooks():
    """
    Retorna la lista de webhooks de la app.
    GET https://api.podio.com/hook/{app_id}/
    """
    headers = get_podio_headers()
    url = f"https://api.podio.com/hook/{PODIO_TAP_APP_ID}/"
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def clear_existing_webhooks():
    """
    Elimina todos los webhooks asociados a la app.
    DELETE https://api.podio.com/hook/{hook_id}
    """
    headers = get_podio_headers()

    try:
        hooks = list_webhooks()
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


def register_podio_webhooks():
    """
    Registra los webhooks necesarios (create, update, delete).
    POST https://api.podio.com/hook/app/{app_id}
    """
    headers = get_podio_headers()
    base_url = f"https://api.podio.com/hook/app/{PODIO_TAP_APP_ID}"

    # La URL pública completa a la que Podio hará POST cuando ocurra el evento.
    # Asegúrate de que PUBLIC_URL termine sin '/' o constrúyela consistentemente.
    target = f"{PUBLIC_URL}/webhook/podio"

    events = ["item.create", "item.update", "item.delete"]
    results = {"created": [], "skipped": [], "errors": []}

    for ev in events:
        payload = {"url": target, "type": ev}
        resp = requests.post(base_url, headers=headers, json=payload)
        if resp.status_code == 200:
            print(f"✅ Webhook '{ev}' registrado")
            results["created"].append(resp.json())
        elif resp.status_code == 409:
            print(f"ℹ️ Webhook '{ev}' ya existía")
            results["skipped"].append(ev)
        else:
            err = {"event": ev, "status": resp.status_code, "text": resp.text}
            print("❌ Error registrando webhook:", err)
            results["errors"].append(err)

    return results
