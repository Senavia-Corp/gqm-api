from src.podio.services.sync_preview import sync_podio_to_db_dry_run

if __name__ == "__main__":
    sync_podio_to_db_dry_run(limit=5)
