
from flask import Blueprint, request, jsonify
from src.podio.podio_auth import get_podio_headers
from src.config import get_podio_app_credentials
import requests

debug_bp = Blueprint("debug", __name__)


@debug_bp.get("/podio/items/<app_type>")
def get_podio_app_items(app_type):
    """
    Endpoint de depuración para obtener todos los items de una app en Podio.
    """
    try:
        app_type = app_type.upper()
        headers = get_podio_headers(app_type)

        # Obtener app_id de la app
        creds = get_podio_app_credentials(app_type)
        app_id = creds["APP_ID"]

        # URL correcta para obtener items
        url = f"https://api.podio.com/item/app/{app_id}/?limit=50"
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        items_json = resp.json()

        return jsonify(items_json), 200

    except requests.exceptions.HTTPError as http_err:
        return jsonify({"error": f"HTTP error: {http_err}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
