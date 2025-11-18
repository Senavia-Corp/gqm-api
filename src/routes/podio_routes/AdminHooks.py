from flask import Blueprint, jsonify
from src.podio.webhooks.test_admin_panel import (
    list_webhooks,
    clear_existing_webhooks,
    register_podio_webhooks
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin/webhooks")


@admin_bp.get("/")
def get_hooks():
    resp = list_webhooks()
    return jsonify(resp), 200


@admin_bp.post("/register")
def register_hooks():
    resp = register_podio_webhooks()
    return jsonify(resp), 200


@admin_bp.delete("/clear")
def clear_hooks():
    ok, resp = clear_existing_webhooks()
    return jsonify({"success": ok, "detail": resp}), 200
