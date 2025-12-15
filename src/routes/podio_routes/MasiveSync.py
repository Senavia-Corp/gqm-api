
from flask import Blueprint, jsonify
from src.podio.services.sync_podio_to_db import sync_podio_to_db


sync_bp = Blueprint("sync_bp", __name__)


# Sincronizar todos los datos desde Podio hacia PostgreSQL


@sync_bp.post("/sync/podio")
def sync_from_podio():
    try:
        sync_podio_to_db()
        return jsonify({"message": "✅ Sincronización completada desde Podio"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
