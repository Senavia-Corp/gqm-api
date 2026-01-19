import requests
from ..qbo_auth import get_valid_access_token


# GET para Bills
def get_bills(realm_id, start=1, limit=300):
    access_token = get_valid_access_token(realm_id)

    base_url = "https://quickbooks.api.intuit.com"
    query = (
        "SELECT * FROM Bill "
        "ORDER BY Id DESC "
        f"STARTPOSITION {start} MAXRESULTS {limit}"
    )

    url = f"{base_url}/v3/company/{realm_id}/query"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/text"
    }

    params = {
        "query": query
    }

    response = requests.get(url, headers=headers, params=params)

    print("QB STATUS:", response.status_code)
    print("QB RESPONSE:", response.text)

    response.raise_for_status()
    return response.json()


# # GET para Bill Payments
def get_bill_payments(realm_id, start=1, limit=200):
    access_token = get_valid_access_token(realm_id)

    base_url = "https://quickbooks.api.intuit.com"
    query = (
        "SELECT * FROM BillPayment "
        "ORDER BY Id DESC "
        f"STARTPOSITION {start} MAXRESULTS {limit}"
    )

    url = f"{base_url}/v3/company/{realm_id}/query"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/text"
    }

    response = requests.get(url, headers=headers, params={"query": query})

    print("QB STATUS:", response.status_code)
    print("QB RESPONSE:", response.text)

    response.raise_for_status()
    return response.json()
