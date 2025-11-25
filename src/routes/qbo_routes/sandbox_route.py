from flask import Blueprint, jsonify
from src.quickbooks.services.customer_services import get_customers

qbo_bp = Blueprint("qbo_bp", __name__)


@qbo_bp.route("/get_customers")
def get_customers_route():
    data = get_customers()
    return jsonify(data)
