import requests
from .qbo_auth import get_valid_access_token


def get_company_info(realm_id):
    access_token = get_valid_access_token(realm_id)

    url = f"https://sandbox-quickbooks.api.intuit.com/v3/company/{realm_id}/companyinfo/{realm_id}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    response = requests.get(url, headers=headers)

    print("QB RESPONSE STATUS:", response.status_code)
    print("QB RESPONSE:", response.text)

    return response.json()
