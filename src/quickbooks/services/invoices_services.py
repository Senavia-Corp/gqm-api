import requests
from ..qbo_auth import get_valid_access_token

# Obtener todos los invoices


def get_invoices(realm_id, start=1, limit=200):
    access_token = get_valid_access_token(realm_id)

    base_url = "https://quickbooks.api.intuit.com"
    query = (
        "SELECT * FROM Invoice "
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


# Obtener invoices por ID del trabajo
def get_invoices_by_job(realm_id, job_code, start=1, limit=100):
    access_token = get_valid_access_token(realm_id)

    base_url = "https://quickbooks.api.intuit.com"
    query = (
        "SELECT * FROM Invoice "
        f"WHERE DocNumber LIKE '{job_code}-%' "
        "ORDER BY Id DESC "
        f"STARTPOSITION {start} MAXRESULTS {limit}"
    )

    url = f"{base_url}/v3/company/{realm_id}/query"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/text"
    }

    # Query se manda en el body
    response = requests.post(url, headers=headers, data=query)

    print("QB STATUS:", response.status_code)
    print("QB QUERY:", query)
    print("QB RESPONSE:", response.text)

    response.raise_for_status()
    return response.json()
