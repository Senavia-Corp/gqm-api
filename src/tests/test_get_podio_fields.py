
from src.podio.podio_auth import get_podio_headers
from src.config import BASE_URL, PODIO_TAP_APP_ID
import requests

if __name__ == "__main__":
    headers = get_podio_headers()
    url = f"{BASE_URL}/app/{PODIO_TAP_APP_ID}"

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    data = response.json()
    fields = data.get("fields", [])

    print(f"\n✅ Campos del App {PODIO_TAP_APP_ID}:\n")
    for f in fields:
        print(
            f"- {f['label']}  ➜  external_id: '{f['external_id']}'  (type: {f['type']})")
