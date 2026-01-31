from flask import Blueprint, request, jsonify
from src.podio.podio_auth import get_podio_headers
from src.config import get_podio_app_credentials
import requests


def filter_items_by_acc_rep(items: list) -> list:
    """
    Filtra items que tengan valor en el campo acc-rep
    y extrae info relevante del usuario.
    """

    results = []

    for item in items:
        fields = item.get("fields", [])

        for f in fields:
            if (
                f.get("type") == "contact"
                and f.get("external_id") == "acc-rep"
            ):
                for v in f.get("values", []):
                    user = v.get("value", {})
                    if user.get("user_id"):
                        results.append({
                            "item_id": item.get("item_id"),
                            "item_title": item.get("title"),
                            "user_id": user.get("user_id"),
                            "name": user.get("name"),
                            "email": user.get("mail"),
                            "profile_id": user.get("profile_id"),
                        })

    return results


# BLUEPRINT PARA FILTRAR POR ACC-REP
podio_filter_bp = Blueprint("podio_filter", __name__)


@podio_filter_bp.get("/podio/items/<app_type>/acc-rep")
def get_podio_items_by_acc_rep(app_type):
    """
    Devuelve los items de una app que tengan acc-rep
    junto con los user_id asociados.
    """

    try:
        app_type = app_type.upper()
        headers = get_podio_headers(app_type)

        creds = get_podio_app_credentials(app_type)
        app_id = creds["APP_ID"]

        url = f"https://api.podio.com/item/app/{app_id}/?limit=100&offset=400"
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()

        items_json = resp.json()
        items = items_json.get("items", [])

        filtered = filter_items_by_acc_rep(items)

        return jsonify({
            "app_type": app_type,
            "total_items": len(items),
            "matches": len(filtered),
            "results": filtered
        }), 200

    except requests.exceptions.HTTPError as http_err:
        return jsonify({"error": f"HTTP error: {http_err}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
