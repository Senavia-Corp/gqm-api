import requests
from ..qbo_auth import get_valid_access_token


# Obtener todos los invoices
def get_invoices(realm_id, start=1, limit=200):
    access_token = get_valid_access_token(realm_id)

    base_url = "https://quickbooks.api.intuit.com"
    query = (
        "SELECT * FROM Invoice "
        "ORDERBY Metadata.LastUpdatedTime DESC "
        f"STARTPOSITION {start} MAXRESULTS {limit}"
    )

    url = f"{base_url}/v3/company/{realm_id}/query"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    params = {
        "query": query,
        "minorversion": 75
    }

    response = requests.get(url, headers=headers, params=params)

    print("QB STATUS:", response.status_code)
    print("QB RESPONSE:", response.text)

    response.raise_for_status()
    return response.json()


def get_invoices_by_job(realm_id, job_code, start=1, limit=100):
    access_token = get_valid_access_token(realm_id)
    base_url = f"https://quickbooks.api.intuit.com/v3/company/{realm_id}/query"

    # Construimos la query en una sola línea limpia
    query_string = f"SELECT * FROM Invoice WHERE DocNumber LIKE '{job_code}%' STARTPOSITION {start} MAXRESULTS {limit}"

    # 'requests' se encargará de codificar correctamente el LIKE y las comillas
    params = {
        "query": query_string,
        "minorversion": 75
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }

    response = requests.get(base_url, headers=headers, params=params)

    print("URL FINAL:", response.url)
    print("QB STATUS:", response.status_code)
    print("QB RESPONSE:", response.text)

    if response.status_code != 200:
        print("QB ERROR DETAIL:", response.text)

    response.raise_for_status()
    return response.json()
