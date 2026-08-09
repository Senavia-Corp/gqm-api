from flask import Blueprint, jsonify, request

from src.podio.webhook.func_hooks import (
    JOB_APP_TYPES,
    clear_existing_webhooks,
    list_webhooks,
    register_podio_webhooks,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin/webhooks")


def _year_or_error(app_type):
    """Las apps de Jobs son por año: ?year= es obligatorio para ellas."""
    year = request.args.get("year", type=int)
    if app_type.upper() in JOB_APP_TYPES and not year:
        return None, (jsonify({
            "detail": f"{app_type} requiere ?year= (apps de Jobs por año)"}), 400)
    return year, None


@admin_bp.get("/<app_type>")
def get_hooks(app_type):
    year, err = _year_or_error(app_type)
    if err:
        return err
    resp = list_webhooks(app_type, year=year)
    return jsonify(resp), 200


@admin_bp.post("/<app_type>/register")
def register_hooks(app_type):
    year, err = _year_or_error(app_type)
    if err:
        return err
    resp = register_podio_webhooks(app_type, year=year)
    return jsonify(resp), 200


@admin_bp.delete("/<app_type>/clear")
def clear_hooks(app_type):
    year, err = _year_or_error(app_type)
    if err:
        return err
    # only_own siempre: jamás borrar hooks ajenos de la app (REG-010)
    ok, resp = clear_existing_webhooks(app_type, year=year, only_own=True)
    return jsonify({"success": ok, "detail": resp}), 200
