
from flask import Blueprint, request, jsonify
import requests

from src.podio.podio_auth import get_podio_headers
from src.config import (
    get_podio_app_credentials,
    get_job_app_credentials
)

debug_bp = Blueprint("debug", __name__)


@debug_bp.get("/podio/items/<app_type>")
def get_podio_app_items(app_type):
    """
    - Apps estáticas: /podio/items/CLI
    - Jobs: /podio/items/QID?year=2026
    """
    try:
        app_type = app_type.upper()
        year = request.args.get("year", type=int)

        # ----------------------------------
        # JOBS (QID / PTL / PAR + year)
        # ----------------------------------
        if year:
            headers = get_podio_headers(app_type, year)
            creds = get_job_app_credentials(year, app_type)
            app_id = creds["APP_ID"]

        # ----------------------------------
        # APPS ESTÁTICAS
        # ----------------------------------
        else:
            headers = get_podio_headers(app_type)
            creds = get_podio_app_credentials(app_type)
            app_id = creds["APP_ID"]

        # ----------------------------------
        # Request a Podio
        # ----------------------------------
        url = f"https://api.podio.com/item/app/{app_id}/?limit=50"
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()

        return jsonify(resp.json()), 200

    except requests.exceptions.HTTPError as http_err:
        return jsonify({
            "status": "error",
            "type": "http",
            "error": str(http_err)
        }), 500

    except Exception as e:
        return jsonify({
            "status": "error",
            "type": "internal",
            "error": str(e)
        }), 500
