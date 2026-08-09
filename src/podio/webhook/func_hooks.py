import re

import requests
from decouple import config as env_config

from src.podio.podio_auth import get_podio_headers
from src.config import PUBLIC_URL, get_podio_app_credentials, get_job_app_credentials
from src.utils.middleware.logs.logs import logger
from src.utils.middleware.retries.retries import retry_api


def redact_hook_url(url: str) -> str:
    """El token del webhook es un secreto: jamás a logs ni a respuestas."""
    return re.sub(r"(token=)[^&]+", r"\1***", url or "")

# Apps de Jobs: una app por año → el hook necesita year (REG-002/REG-010)
JOB_APP_TYPES = {"QID", "PTL", "PAR"}
# Apps con sync de relaciones vs simples (rutas reales de Webhook_bp.py)
RELATION_APP_TYPES = {"CLI", "SUBC"}
NO_RELATION_APP_TYPES = {"PMC", "BDEP"}
# Apps cuyos adjuntos procesa process_file_change_event (ATTACHMENT_MODEL_MAP)
FILE_CHANGE_APP_TYPES = {"CLI", "SUBC", "PMC", "BDEP"}

ITEM_EVENTS = ["item.create", "item.update", "item.delete"]


def get_app_id(app_type: str, year: int | None = None):
    """Resuelve el APP_ID real: por año para Jobs, estática para el resto."""
    app_type = app_type.upper()
    if app_type in JOB_APP_TYPES:
        if not year:
            raise ValueError(f"{app_type} requiere 'year' (las apps de Jobs son por año)")
        return get_job_app_credentials(year, app_type)["APP_ID"]
    return get_podio_app_credentials(app_type)["APP_ID"]


def build_webhook_target(app_type: str, year: int | None = None) -> str:
    """URL de destino que SÍ existe en Webhook_bp.py (antes apuntaba a 404)."""
    app_type = app_type.upper()
    if app_type in JOB_APP_TYPES:
        if not year:
            raise ValueError(f"{app_type} requiere 'year'")
        path = f"/webhook/podio/jobs/{app_type}/{year}"
    elif app_type in RELATION_APP_TYPES:
        path = f"/webhook/podio/others/relations/{app_type}"
    elif app_type in NO_RELATION_APP_TYPES:
        path = f"/webhook/podio/others/no_relations/{app_type}"
    else:
        raise ValueError(f"app_type sin ruta de webhook: {app_type}")

    target = f"{PUBLIC_URL.rstrip('/')}{path}"

    # Podio no firma sus webhooks: el token en la URL es la autenticación
    # (la validación del lado del API se activa en el Bloque 2).
    token = env_config("PODIO_WEBHOOK_TOKEN", default="")
    if token:
        target = f"{target}?token={token}"
    else:
        logger.warning(
            "PODIO_WEBHOOK_TOKEN no configurado: el webhook de %s se registra "
            "SIN token de autenticación", app_type)
    return target


@retry_api(max_retries=3, backoff=2)
def list_webhooks(app_type: str, year: int | None = None):
    """Lista los webhooks de la app indicada (por año si es de Jobs)."""
    headers = get_podio_headers(app_type, year=year)
    app_id = get_app_id(app_type, year=year)

    url = f"https://api.podio.com/hook/app/{app_id}/"
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


@retry_api(max_retries=3, backoff=2)
def clear_existing_webhooks(app_type: str, year: int | None = None, only_own: bool = True):
    """Elimina webhooks de la app. Por defecto SOLO los que apuntan a
    PUBLIC_URL (REG-010: antes borraba TODOS los hooks de la app, incluidos
    los ajenos)."""
    headers = get_podio_headers(app_type, year=year)

    try:
        hooks = list_webhooks(app_type, year=year)
    except Exception as e:
        print(f"❌ No se pudo listar webhooks: {e}")
        return False, str(e)

    if not hooks:
        print("ℹ️ No hay webhooks para borrar")
        return True, "No hooks"

    own_prefix = PUBLIC_URL.rstrip("/")
    errors = []
    skipped = 0
    for hook in hooks:
        hook_id = hook.get("hook_id") or hook.get("hookId") or hook.get("id")
        if not hook_id:
            continue

        hook_url = hook.get("url") or ""
        is_own = hook_url == own_prefix or hook_url.startswith((own_prefix + "/", own_prefix + "?"))
        if only_own and not is_own:
            skipped += 1
            print(f"⏭️ Webhook {hook_id} ajeno ({redact_hook_url(hook_url)[:60]}) — no se toca")
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

    if skipped:
        print(f"ℹ️ {skipped} webhooks ajenos conservados")
    return (len(errors) == 0), errors


@retry_api(max_retries=3, backoff=2)
def register_podio_webhooks(app_type: str, year: int | None = None):
    """Registra los webhooks de la app en las rutas reales del API.

    - Jobs (QID/PTL/PAR): item.create/update/delete → /jobs/<type>/<year>,
      credenciales de la app real del año (get_job_app_credentials).
    - CLI/SUBC/PMC/BDEP: item.* + file.change (adjuntos) → /others/...
    """
    app_type = app_type.upper()
    headers = get_podio_headers(app_type, year=year)
    app_id = get_app_id(app_type, year=year)

    base_url = f"https://api.podio.com/hook/app/{app_id}"
    target = build_webhook_target(app_type, year=year)

    events = list(ITEM_EVENTS)
    if app_type in FILE_CHANGE_APP_TYPES:
        events.append("file.change")

    # target redactado: el token no sale ni por logs ni por la respuesta HTTP
    results = {"target": redact_hook_url(target), "created": [], "skipped": [], "errors": []}

    for ev in events:
        payload = {"url": target, "type": ev}
        resp = requests.post(base_url, headers=headers, json=payload)

        if resp.status_code == 200:
            print(f"✅ Webhook '{ev}' registrado en {app_type} → {redact_hook_url(target)}")
            results["created"].append(resp.json())
        elif resp.status_code == 409:
            print(f"ℹ️ Webhook '{ev}' ya existía en {app_type}")
            results["skipped"].append(ev)
        else:
            err = {"event": ev, "status": resp.status_code, "text": resp.text}
            print("❌ Error registrando webhook:", err)
            results["errors"].append(err)

    return results
