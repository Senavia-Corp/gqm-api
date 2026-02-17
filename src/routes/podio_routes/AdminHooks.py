
from flask import Blueprint, jsonify
from src.podio.webhook.func_hooks import (
    list_webhooks,
    clear_existing_webhooks,
    register_podio_webhooks
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin/webhooks")


@admin_bp.get("/<app_type>")
def get_hooks(app_type):
    resp = list_webhooks(app_type)
    return jsonify(resp), 200


@admin_bp.post("/<app_type>/register")
def register_hooks(app_type):
    resp = register_podio_webhooks(app_type)
    return jsonify(resp), 200


@admin_bp.delete("/<app_type>/clear")
def clear_hooks(app_type):
    ok, resp = clear_existing_webhooks(app_type)
    return jsonify({"success": ok, "detail": resp}), 200
