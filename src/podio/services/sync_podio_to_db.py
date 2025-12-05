

from src.podio.services.job_services import podio_jobs_router
from src.podio.services.client_services import podio_clients_router
from src.podio.services.tasks_services import podio_tasks_router
from src.utils.mappers.from_podio.job_mapper import map_podio_item_to_job
from src.utils.mappers.from_podio.client_mapper import map_podio_item_to_client
from src.utils.mappers.from_podio.tasks_mapper import map_podio_item_to_task
from src.models.JobModel import Job
from src.models.ClientModel import Client
from src.models.TasksModel import Tasks
from src.database.db_sqlmodel import get_session
from sqlmodel import select
from src.utils.middleware.retries.retries import retry_db

# SINCRONIZACIÓN MASIVA

# ============================
# Función genérica por cada App
# ============================


def fetch_all_items_from_app(app_type: str):
    """
    Descarga TODOS los items de una App (QID, PTL o PAR),
    manejando paginación automáticamente.
    """
    service = podio_jobs_router.get_service(app_type)

    all_items = []
    offset = 0
    limit = 50

    while True:
        items = service.get_items(limit=limit, offset=offset)
        if not items:
            break

        all_items.extend(items)
        offset += limit

    return all_items


# ======================
#   SINCRONIZACIÓN JOBS
# ======================

@retry_db(max_retries=3, delay=1)
def sync_jobs():

    APPS = ["QID", "PTL", "PAR"]

    print(f"🚀 Iniciando sincronización de Jobs para apps: {APPS}")

    with get_session() as session:

        for app_type in APPS:
            print(f"\n==============================")
            print(f"🔄 Sincronizando App: {app_type}")
            print(f"==============================")

            items = fetch_all_items_from_app(app_type)
            print(f"📥 Recibidos {len(items)} items desde Podio ({app_type})")

            # Procesar cada item
            for item in items:
                mapped = map_podio_item_to_job(item)

                # 1. Buscar si ya existe
                existing = session.exec(
                    select(Job).where(Job.podio_item_id ==
                                      mapped["podio_item_id"])
                ).first()

                if existing:
                    # 2. Actualizar
                    for key, value in mapped.items():
                        setattr(existing, key, value)
                    print(f"🟡 Actualizado: {existing.Project_name}")

                else:
                    # 3. Crear
                    new_job = Job(**mapped)
                    session.add(new_job)
                    print(f"🟢 Insertado: {new_job.Project_name}")

            session.commit()

    print("✅ Sincronización completa de TODOS los Jobs.")


# ======================
#   SINCRONIZACIÓN CLIENTS
# ======================

@retry_db(max_retries=3, delay=1)
def sync_clients():

    print("🚀 Iniciando sincronización de Clients")

    with get_session() as session:

        # Obtener items desde Podio usando el router
        client_service = podio_clients_router.get_service()
        items = client_service.get_items()
        print(f"📥 Recibidos {len(items)} items desde Podio (CLI)")

        for item in items:
            mapped = map_podio_item_to_client(item)

            # 1. Buscar si ya existe
            existing = session.exec(
                select(Client).where(
                    Client.podio_item_id == mapped["podio_item_id"])
            ).first()

            if existing:
                # 2. Actualizar
                for key, value in mapped.items():
                    setattr(existing, key, value)
                # Cambia al campo que uses
                print(f"🟡 Actualizado: {existing.name}")

            else:
                # 3. Crear
                new_client = Client(**mapped)
                session.add(new_client)
                print(f"🟢 Insertado: {new_client.name}")

        session.commit()

    print("✅ Sincronización completa de TODOS los Clients.")


# ======================
#   SINCRONIZACIÓN TASKS
# ======================

@retry_db(max_retries=3, delay=1)
def sync_tasks():

    print("🚀 Iniciando sincronización de Tasks")

    with get_session() as session:

        # Obtener items desde Podio usando el router
        task_service = podio_tasks_router.get_service()
        items = task_service.get_items()
        print(f"📥 Recibidos {len(items)} items desde Podio (TASK)")

        for item in items:
            mapped = map_podio_item_to_task(item)

            # 1. Buscar si ya existe
            existing = session.exec(
                select(Tasks).where(
                    Tasks.podio_item_id == mapped["podio_item_id"])
            ).first()

            if existing:
                # 2. Actualizar
                for key, value in mapped.items():
                    setattr(existing, key, value)
                # Cambia al campo principal que uses en Task
                print(f"🟡 Actualizado: {existing.name}")

            else:
                # 3. Crear
                new_task = Tasks(**mapped)
                session.add(new_task)
                print(f"🟢 Insertado: {new_task.name}")

        session.commit()

    print("✅ Sincronización completa de TODAS las Tasks.")


# =========================
#  Punto de entrada global
# =========================

def sync_podio_to_db():
    print("🚀 Iniciando sincronización general desde Podio...")

    sync_jobs()
    sync_clients()
    sync_tasks()

    print("✅ Sincronización completa.")
