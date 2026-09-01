import re

import requests
from decouple import config as env_config

from src.podio.podio_auth import get_podio_headers
from src.config import PUBLIC_URL, get_podio_app_credentials, get_job_app_credentials
from src.utils.middleware.logs.logs import logger
from src.utils.middleware.retries.retries import retry_api


def redact_hook_url(url: str) -> str:
    """El token del webhook es un secreto: jamás a logs ni a respuestas.

    Oculta las DOS formas: `?token=` (legado) y el token como último segmento de
    la ruta (la actual, porque Podio descarta el query string al entregar). Sin
    esta segunda parte el secreto salía por los logs y por la respuesta HTTP de
    /admin/webhooks/<app>/register.
    """
    limpia = re.sub(r"(token=)[^&]+", r"\1***", url or "")
    secreto = env_config("PODIO_WEBHOOK_TOKEN", default="")
    if secreto:
        limpia = limpia.replace(secreto, "***")
    return limpia

# Apps de Jobs: una app por año → el hook necesita year (REG-002/REG-010)
JOB_APP_TYPES = {"QID", "PTL", "PAR"}
# Apps con sync de relaciones vs simples (rutas reales de Webhook_bp.py)
RELATION_APP_TYPES = {"CLI", "SUBC"}
NO_RELATION_APP_TYPES = {"PMC", "BDEP"}
# Apps cuyos adjuntos procesa process_file_change_event (ATTACHMENT_MODEL_MAP)
#
# QID/PTL/PAR estaban FUERA de este conjunto, asi que register_podio_webhooks
# no registraba file.change para ellas... pero el receptor de jobs SI lo
# implementa (Webhook_bp.py, rama "file.change" de podio_jobs_webhook) y las
# apps reales YA tienen ese hook puesto a mano. Resultado: re-registrar los
# hooks perdia la sincronizacion de adjuntos de los jobs sin avisar. El runbook
# lo llevaba anotado como trampa del cutover; esto lo arregla en el origen.
FILE_CHANGE_APP_TYPES = {"CLI", "SUBC", "PMC", "BDEP", "QID", "PTL", "PAR"}

ITEM_EVENTS = ["item.create", "item.update", "item.delete"]
EVENTOS_VALIDOS = set(ITEM_EVENTS) | {"file.change"}

# El token se concatena a la RUTA sin escapar (`build_webhook_target`). Un `/`
# mete un segmento de mas y Flask NO enruta: mueren las entregas *y* el
# hook.verify, con lo que el hook se queda `inactive` para siempre... y
# /register responde 200 igual. Un `%` abre una secuencia de escape y un `+`
# o un `=` se comen la comparacion. `openssl rand -base64 32` produce `/` casi
# la mitad de las veces, asi que el error es probable, silencioso y permanente.
#
# Exigir hexadecimal lo hace imposible por construccion. `secrets.token_hex(32)`
# da 64 caracteres, muy por encima del minimo.
_TOKEN_HEX = re.compile(r"^[0-9a-f]{32,}$")


def token_de_webhook() -> str:
    """El token vigente, o "" si no hay. Lanza si lo hay y esta mal formado.

    Falla ANTES de registrar, nunca despues: un token ilegal grabado en 48 URLs
    queda congelado ahi y el sintoma es 404 en todo, sin un solo error visible.
    El mensaje no incluye el valor: es un secreto y acaba en logs.
    """
    token = env_config("PODIO_WEBHOOK_TOKEN", default="")
    if token and not _TOKEN_HEX.match(token):
        # El motivo exacto, no uno generico: durante un cutover, un diagnostico
        # que apunta al sitio equivocado cuesta mas que el fallo.
        malos = sorted(set(c for c in token if c not in "0123456789abcdef"))
        motivos = []
        if len(token) < 32:
            motivos.append(f"tiene {len(token)} caracteres y el minimo es 32")
        if malos:
            motivos.append(f"contiene {len(malos)} caracter(es) fuera de [0-9a-f]"
                           + (" (incluida una BARRA, que parte la ruta)" if "/" in malos else ""))
        raise ValueError(
            "PODIO_WEBHOOK_TOKEN mal formado: " + "; ".join(motivos) + ". "
            "Debe casar ^[0-9a-f]{32,}$. Genera uno con "
            "`python3 -c \'import secrets; print(secrets.token_hex(32))\'`.")
    return token


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
    token = token_de_webhook()
    if token:
        # En la RUTA, no en el query: Podio descarta el query string al entregar
        # (comprobado en los logs el 10-ago-2026). El prefijo se mantiene
        # (/webhook/podio/jobs/...) para no romper la whitelist publica de
        # main.py, que filtra por prefijo.
        target = f"{target}/{token}"
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
        return False, {"errors": [str(e)]}

    if not hooks:
        print("ℹ️ No hay webhooks para borrar")
        return True, {"errors": [], "detalle": "no habia hooks"}

    own_prefix = PUBLIC_URL.rstrip("/")

    # GUARDA DEL CUTOVER. `is_own` decide por PREFIJO de PUBLIC_URL, y los hooks
    # NUEVOS —los que llevan el token al final de la ruta— comparten ese mismo
    # prefijo. Sin esta guarda, un /clear durante o despues del cutover borra
    # las DOS generaciones y deja la app con CERO hooks: sincronizacion muerta,
    # y con `success: true` porque este endpoint responde 200 pase lo que pase.
    #
    # Peor aun en el orden real de la operacion: los 48 viejos los creo una
    # cuenta de usuario (medido el 1-sep-2026), asi que el app token no puede
    # borrarlos y devuelven 403 — mientras que los nuevos los crea la app y si
    # se borran. Es decir, /clear borraria EXACTAMENTE los que hay que conservar.
    #
    # Con la guarda, /clear solo puede tocar hooks legado (sin el token vigente),
    # que es justo para lo que sirve durante el cutover.
    token_vigente = token_de_webhook()
    conservados_por_token = 0

    errors = []
    skipped = 0
    for hook in hooks:
        hook_id = hook.get("hook_id") or hook.get("hookId") or hook.get("id")
        if not hook_id:
            continue

        hook_url = hook.get("url") or ""
        if token_vigente and token_vigente in hook_url:
            conservados_por_token += 1
            print(f"🛡️ Webhook {hook_id} lleva el token vigente — no se toca")
            continue

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
    if conservados_por_token:
        print(f"🛡️ {conservados_por_token} webhooks con el token vigente conservados")
    return (len(errors) == 0), {"errors": errors,
                                "omitidos_ajenos": skipped,
                                "conservados_por_token": conservados_por_token}


def borrar_hook(hook_id, app_type: str, year: int | None = None):
    """Borra UN hook por su id. Sin heuristicas de prefijo ni de token.

    Existe porque `clear_existing_webhooks` no sirve para dos cosas que si
    hacen falta:

      * Es el camino de vuelta del cutover. La guarda que impide que /clear
        borre la generacion del token vigente tambien impide deshacerla, y sin
        rollback por API la unica salida serian 48 borrados a mano en la UI.
        Los hooks NUEVOS los crea la aplicacion, asi que el app token si puede
        borrarlos (los 48 VIEJOS los creo una cuenta de usuario: daran 403).
      * /clear decide por prefijo de PUBLIC_URL y borra en bloque. Aqui se
        borra exactamente lo que se nombra.

    No lleva @retry_api a proposito: un DELETE que "falla" pero llego a
    aplicarse no debe repetirse a ciegas. El 404 se trata como exito porque el
    estado final es el mismo — no existe.
    """
    headers = get_podio_headers(app_type, year=year)
    resp = requests.delete(f"https://api.podio.com/hook/{hook_id}",
                           headers=headers, timeout=30)

    if resp.status_code in (200, 202, 204):
        print(f"🗑️ Webhook {hook_id} eliminado")
        return True, {"hook_id": hook_id, "status": resp.status_code}
    if resp.status_code == 404:
        print(f"ℹ️ Webhook {hook_id} ya no existe")
        return True, {"hook_id": hook_id, "status": 404, "detalle": "ya no existia"}
    if resp.status_code == 403:
        # El caso esperado con los 48 viejos: los creo una cuenta de usuario.
        print(f"⛔ Webhook {hook_id}: 403 — no lo creo la aplicacion, "
              f"hay que borrarlo desde la UI de Podio")
    return False, {"hook_id": hook_id, "status": resp.status_code,
                   "text": resp.text[:300]}


@retry_api(max_retries=3, backoff=2)
def solicitar_verificacion_hook(hook_id, app_type: str, year: int | None = None):
    """Pide a Podio que mande el `hook.verify` de un hook concreto.

    Por que existe: un hook nace `inactive` y NO dispara jamas hasta que se
    verifica. La verificacion la dispara Podio por su cuenta... o no, y el repo
    no tenia forma de pedirla: `/hook/<id>/verify/request` no aparecia en
    ninguna linea. Se midio en dev el 10-ago-2026 que Podio la manda sola; en
    produccion NUNCA se ha medido.

    Sin esto, un hook que se quede `inactive` no tiene camino de vuelta y la
    sincronizacion de esa app queda muerta en silencio — no hay cron, alerta ni
    test que lo detecte. Es la unica recuperacion del riesgo n.º 1 del cutover.

    La respuesta al `hook.verify` ya esta implementada
    (`parse_and_validate_webhook` → `activate_podio_webhook`, que valida el
    `code` contra `/hook/<id>/verify/validate`).
    """
    headers = get_podio_headers(app_type, year=year)
    url = f"https://api.podio.com/hook/{hook_id}/verify/request"
    resp = requests.post(url, headers=headers, timeout=30)

    if resp.status_code in (200, 202, 204):
        print(f"📨 Verificacion solicitada para el hook {hook_id} ({app_type})")
        return True, {"hook_id": hook_id, "status": resp.status_code}
    return False, {"hook_id": hook_id, "status": resp.status_code,
                   "text": resp.text[:300]}


@retry_api(max_retries=3, backoff=2)
def register_podio_webhooks(app_type: str, year: int | None = None,
                            events: list[str] | None = None):
    """Registra los webhooks de la app en las rutas reales del API.

    - Jobs (QID/PTL/PAR): item.create/update/delete → /jobs/<type>/<year>,
      credenciales de la app real del año (get_job_app_credentials).
    - CLI/SUBC/PMC/BDEP: item.* + file.change (adjuntos) → /others/...

    `events` registra EXACTAMENTE los indicados, en vez del juego por defecto.

    Hace falta porque el juego por defecto no representa la realidad: como
    FILE_CHANGE_APP_TYPES contiene las 7 familias, el `if` de mas abajo siempre
    entra y toda app recibe los 4 eventos. Las apps de produccion no estan asi
    —PMC, QID/2024, PTL/2024 y PAR/2024 tienen 3, sin `file.change`—, de modo
    que re-registrar sin `events` les añadiria un hook que hoy no tienen y
    empezaria a subir adjuntos de años cerrados a Cloudinary.

    El cutover del token se guia por el censo de los hooks reales y pasa la
    lista por aqui, para que rotar el token no cambie de paso la topologia.
    """
    app_type = app_type.upper()
    headers = get_podio_headers(app_type, year=year)
    app_id = get_app_id(app_type, year=year)

    base_url = f"https://api.podio.com/hook/app/{app_id}"
    target = build_webhook_target(app_type, year=year)

    if events is None:
        events = list(ITEM_EVENTS)
        if app_type in FILE_CHANGE_APP_TYPES:
            events.append("file.change")
    else:
        desconocidos = [e for e in events if e not in EVENTOS_VALIDOS]
        if desconocidos:
            raise ValueError(
                f"eventos no reconocidos: {desconocidos}. "
                f"Validos: {sorted(EVENTOS_VALIDOS)}")
        # Sin duplicados y en el orden pedido. Que Podio responda 409 a un
        # duplicado exacto no esta comprobado, asi que no se depende de ello:
        # se elimina aqui y no se manda la peticion.
        events = list(dict.fromkeys(events))
        if not events:
            raise ValueError("la lista de eventos esta vacia")

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
