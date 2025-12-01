

from src.podio.services.job_services import get_podio_jobs
from src.utils.mappers.job_mapper import map_podio_item_to_job
from src.models.JobModel import Job
from src.database.db_sqlmodel import get_session
from sqlmodel import select
from src.utils.middleware.retries.retries import retry_db

# SINCRONIZACIÓN MASIVA


@retry_db(max_retries=3, delay=1)
def sync_jobs():

    # Sincroniza los Jobs desde Podio a PostgreSQL.

    items = get_podio_jobs()
    print(f"🔄 Sincronizando {len(items)} Jobs desde Podio...")

    with get_session() as session:
        for item in items:
            print("🟦 Item completo recibido de Podio:")
            print(item)
            print("\n\n🟨 Campo id-projects-workorder:")
            for f in item.get("fields", []):
                if f.get("external_id") == "id-projects-workorder":
                    print(f)
            mapped = map_podio_item_to_job(item)

            # Buscar si ya existe un registro con el mismo podio_item_id
            existing = session.exec(
                select(Job).where(Job.podio_item_id == mapped["podio_item_id"])
            ).first()

            if existing:
                # Actualizar los campos
                for key, value in mapped.items():
                    setattr(existing, key, value)
                print(f"🟡 Actualizado: {existing.Project_name}")
            else:
                # Crear nuevo registro
                new_job = Job(**mapped)
                session.add(new_job)
                print(f"🟢 Insertado: {new_job.Project_name}")

        session.commit()

    print("✅ Sincronización de Jobs completada.")


# ===================================================
# Función general:

def sync_podio_to_db():

    # Punto de entrada general para sincronizar todas las apps de Podio
    print("🚀 Iniciando sincronización general desde Podio...")

    sync_jobs()

    print("✅ Sincronización completa de todas las entidades.")
