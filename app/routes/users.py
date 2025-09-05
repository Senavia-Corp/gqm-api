from flask import Blueprint, request, jsonify
from ..controllers.users_controller import create_user

bp = Blueprint("users", __name__)

@bp.post("")
def create_user_route():
    payload = request.get_json(silent=True) or {}
    result = create_user(payload)
    return jsonify(result), 201