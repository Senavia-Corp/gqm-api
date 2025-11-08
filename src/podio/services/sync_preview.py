from src.podio.services.job_services import get_podio_items
from src.utils.mappers.job_mapper import map_podio_item_to_job


def sync_podio_to_db_dry_run(limit=10):
    """
    Versión de prueba: solo imprime los datos que se traerían de Podio
    y cómo quedarían mapeados antes de guardarlos en PostgreSQL.
    """
    print("⏳ Obteniendo items desde Podio...")
    items = get_podio_items(limit=limit)
    print(f"✅ Se obtuvieron {len(items)} items.\n")

    for i, item in enumerate(items, start=1):
        mapped = map_podio_item_to_job(item)
        print(f"🧩 Item #{i} — Podio ID: {mapped.get('podio_item_id')}")
        print("------------------------------------------------")
        for k, v in mapped.items():
            print(f"{k}: {v}")
        print("------------------------------------------------\n")

    print("🏁 Fin de vista previa (no se modificó la base de datos).")
