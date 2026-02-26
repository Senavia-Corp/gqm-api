import requests
from ..qbo_auth import get_valid_access_token


# FUNCIÓN BASE GENÉRICA PARA HACER PEDIDOS A QBO
def qbo_query(realm_id: str, query: str, start: int = 1, limit: int = 100):
    access_token = get_valid_access_token(realm_id)

    url = f"https://quickbooks.api.intuit.com/v3/company/{realm_id}/query"

    final_query = (
        f"{query} "
        f"STARTPOSITION {start} MAXRESULTS {limit}"
    )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    params = {
        "query": final_query,
        "minorversion": 75
    }

    response = requests.get(url, headers=headers, params=params)

    print("QB URL:", response.url)
    print("QB STATUS:", response.status_code)

    if response.status_code != 200:
        print("QB ERROR:", response.text)

    response.raise_for_status()

    return response.json()


# -------------------- GET POR QBO_ID -------------------- #
def qbo_get_by_id(realm_id, entity_type, entity_id):
    """Trae una entidad específica por su ID desde QBO"""
    # Reutiliza lógica de qbo_query pero filtrando por ID
    query = f"SELECT * FROM {entity_type} WHERE Id = '{entity_id}'"
    response = qbo_query(realm_id, query)

    # QBO devuelve { "QueryResponse": { "Bill": [...] } }
    entities = response.get("QueryResponse", {}).get(entity_type, [])
    return entities[0] if entities else None
