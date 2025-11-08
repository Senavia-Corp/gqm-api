from src.podio.services.job_services import get_podio_items

if __name__ == "__main__":
    try:
        items = get_podio_items(limit=5)
        print(f"✅ Se obtuvieron {len(items)} items desde Podio.")
        for i, item in enumerate(items, start=1):
            print(f"{i}. {item.get('title')}")
    except Exception as e:
        print("❌ Error:", e)

for item in items:
    print(f"\nTítulo: {item.get('title')}")
    print("Campos disponibles:")
    for field in item.get("fields", []):
        print(f"  - {field['external_id']}: {field.get('values')}")
