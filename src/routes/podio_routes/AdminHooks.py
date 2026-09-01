from flask import Blueprint, jsonify, request

from src.podio.webhook.func_hooks import (
    EVENTOS_VALIDOS,
    JOB_APP_TYPES,
    borrar_hook,
    clear_existing_webhooks,
    list_webhooks,
    redact_hook_url,
    register_podio_webhooks,
    solicitar_verificacion_hook,
    token_de_webhook,
)
from src.utils.middleware.exceptions_handler import handle_exceptions

admin_bp = Blueprint("admin", __name__, url_prefix="/admin/webhooks")


def _year_or_error(app_type):
    """Las apps de Jobs son por año: ?year= es obligatorio para ellas."""
    year = request.args.get("year", type=int)
    if app_type.upper() in JOB_APP_TYPES and not year:
        return None, (jsonify({
            "detail": f"{app_type} requiere ?year= (apps de Jobs por año)"}), 400)
    return year, None


@admin_bp.get("/<app_type>")
@handle_exceptions()
def get_hooks(app_type):
    year, err = _year_or_error(app_type)
    if err:
        return err
    resp = list_webhooks(app_type, year=year)
    # Los hooks propios llevan ?token= en la URL: redactar antes de responder
    for hook in resp if isinstance(resp, list) else []:
        if isinstance(hook, dict) and hook.get("url"):
            hook["url"] = redact_hook_url(hook["url"])
    return jsonify(resp), 200


def _events_or_error():
    """`?events=item.create,item.update` → lista, o None para el juego por defecto.

    Sin esto el registro crea SIEMPRE los 4 eventos, y las apps de produccion no
    estan asi: PMC y las tres de 2024 tienen 3. Re-registrarlas sin acotar les
    añade un `file.change` que hoy no tienen.
    """
    crudo = request.args.get("events")
    if crudo is None:
        return None, None
    events = [e.strip() for e in crudo.split(",") if e.strip()]
    if not events:
        return None, (jsonify({"detail": "?events= vino vacio"}), 400)
    desconocidos = [e for e in events if e not in EVENTOS_VALIDOS]
    if desconocidos:
        return None, (jsonify({
            "detail": f"eventos no reconocidos: {desconocidos}",
            "validos": sorted(EVENTOS_VALIDOS)}), 400)
    return events, None


@admin_bp.post("/<app_type>/register")
@handle_exceptions()
def register_hooks(app_type):
    year, err = _year_or_error(app_type)
    if err:
        return err
    events, err = _events_or_error()
    if err:
        return err

    # El token se valida AQUI, antes de entrar en register_podio_webhooks: esa
    # va envuelta en @retry_api, que atrapa Exception y reintenta 3 veces con
    # backoff — un fallo de configuracion costaria 6 s y un log CRITICAL que no
    # describe el problema. La barrera de verdad sigue en build_webhook_target.
    try:
        token_de_webhook()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 400

    resp = register_podio_webhooks(app_type, year=year, events=events)
    return jsonify(resp), 200


@admin_bp.post("/<app_type>/verify/<int:hook_id>")
@handle_exceptions()
def verify_hook(app_type, hook_id):
    """Pide a Podio el `hook.verify` de un hook que sigue `inactive`.

    Un hook `inactive` no dispara jamas y nada lo detecta: no hay cron, ni
    alerta, ni test. Hasta ahora tampoco habia forma de pedir la verificacion.
    """
    year, err = _year_or_error(app_type)
    if err:
        return err
    ok, detalle = solicitar_verificacion_hook(hook_id, app_type, year=year)
    return jsonify({"success": ok, "detail": detalle}), (200 if ok else 502)


@admin_bp.delete("/<app_type>/hook/<int:hook_id>")
@handle_exceptions()
def delete_hook(app_type, hook_id):
    """Borra UN hook por id. Es el camino de vuelta del cutover.

    `/clear` no vale: borra en bloque por prefijo de PUBLIC_URL y ademas
    conserva a proposito la generacion del token vigente.
    """
    year, err = _year_or_error(app_type)
    if err:
        return err
    ok, detalle = borrar_hook(hook_id, app_type, year=year)
    return jsonify({"success": ok, "detail": detalle}), (200 if ok else 502)


@admin_bp.delete("/<app_type>/clear")
@handle_exceptions()
def clear_hooks(app_type):
    year, err = _year_or_error(app_type)
    if err:
        return err
    # /clear tambien lee el token: lo necesita para saber que hooks son de la
    # generacion nueva y NO tocarlos. Si esta mal formado no puede distinguirlos,
    # asi que se niega — fallar cerrado aqui es lo correcto: borrar sin poder
    # identificar la generacion vigente es como se deja una app en cero hooks.
    try:
        token_de_webhook()
    except ValueError as e:
        return jsonify({"detail": str(e)}), 400

    # only_own siempre: jamás borrar hooks ajenos de la app (REG-010)
    ok, resp = clear_existing_webhooks(app_type, year=year, only_own=True)
    return jsonify({"success": ok, "detail": resp}), 200
