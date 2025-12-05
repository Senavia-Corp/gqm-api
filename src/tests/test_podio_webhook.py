import json
from src.utils.get_podio_items import get_podio_item
from src.utils.mappers.from_podio.job_mapper import map_podio_item_to_job
from main import create_app
from src.database.db_sqlmodel import get_session
from src.models.JobModel import Job


def test_get_item_and_map():
    TEST_ITEM_ID = 3196415445

    # Obtener el item completo desde Podio
    item_data = get_podio_item(TEST_ITEM_ID)
    assert "item_id" in item_data, "No se recibió item_id desde Podio"
    print("\n📦 Item recibido correctamente.")

    # Mapear el item al formato PostgreSQL
    job_data = map_podio_item_to_job(item_data)
    print("🧭 Mapeo Job listo:", json.dumps(
        job_data, indent=2, ensure_ascii=False))
    assert job_data.get("ID_Jobs") is not None, "El mapeo no devolvió ID_Jobs"
    print("✅ Test de mapeo exitoso.")


def test_webhook_endpoint():
    app = create_app()
    client = app.test_client()

    # Obtener el item de prueba desde Podio
    item_data = get_podio_item(3196415445)
    job_data = map_podio_item_to_job(item_data)

    # Revisar si ya existe en PostgreSQL
    with get_session() as session:
        existing = session.get(Job, job_data["ID_Jobs"])
        if existing:
            print(
                f"⚠️ Job {job_data['ID_Jobs']} ya existe en PostgreSQL, se omite inserción.")
        else:
            fake_payload = {
                "type": "item.create",
                "item_id": item_data["item_id"],
                "item": item_data
            }

            response = client.post(
                "/webhook/podio",
                data=json.dumps(fake_payload),
                content_type="application/json"
            )

            print(f"\n📩 Respuesta del endpoint: {response.status_code}")
            print(response.get_json())
            assert response.status_code == 200, "Webhook no respondió correctamente"
            print("✅ Webhook test exitoso.")


# -----------------------
# Ejecutar test
# -----------------------
if __name__ == "__main__":
    print("\n=== Probando get_item_and_map() ===")
    test_get_item_and_map()

    print("\n=== Probando webhook_endpoint() ===")
    test_webhook_endpoint()
