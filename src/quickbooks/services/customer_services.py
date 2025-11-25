import os
import requests
from ..qbo_auth import refresh_access_token
from flask import Blueprint, jsonify

# PARA OBTENER EL TOKEN VÁLIDO


def get_valid_access_token():
    refresh_token = os.getenv("QBO_REFRESH_TOKEN")
    tokens = refresh_access_token(refresh_token)
    access_token = tokens.get("access_token")
    new_refresh_token = tokens.get("refresh_token")
    print("Nuevo refresh token:", new_refresh_token)
    return access_token


# PARA HACER EL GET A CUSTOMERS DEL SANDBOX
def get_customers():
    access_token = get_valid_access_token()
    company_id = os.getenv("QBO_COMPANY_ID")
    url = f"https://sandbox-quickbooks.api.intuit.com/v3/company/{company_id}/query"
    query = "SELECT * FROM Customer"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/text"
    }
    response = requests.post(url, headers=headers, data=query)
    return response.json()
