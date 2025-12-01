
from src.podio.podio_auth import get_podio_headers

if __name__ == "__main__":
    try:
        headers = get_podio_headers()
        print("Headers generados correctamente:")
        print(headers)
    except Exception as e:
        print("❌ Error:", e)
