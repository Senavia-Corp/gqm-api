

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
from src.utils.id_generator import generate_custom_id

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

            for item in items:
                # mapear item → dict
                mapped = map_podio_item_to_job(item, session)

                # DEBUG de relaciones
                client_ref = mapped.get("ID_Client")
                print(f"Related Client: {client_ref}")

                # 1. Buscar si ya existe
                existing = session.exec(
                    select(Job).where(Job.podio_item_id ==
                                      mapped["podio_item_id"])
                ).first()

                if existing:  # 2. Buscar si necesita cambios o queda igual.
                    changes = {}
                    for field, new_value in mapped.items():
                        old_value = getattr(existing, field, None)

                        # Detectar cambios reales
                        if old_value != new_value and new_value is not None:
                            changes[field] = new_value

                    if not changes:
                        print(
                            f"⚪ Job {existing.ID_Jobs} ya existe — sin cambios")
                        continue

                    # Aplicar cambios
                    for field, value in changes.items():
                        setattr(existing, field, value)

                    print(
                        f"🟡 Actualizado Job {existing.ID_Jobs} → Campos cambiados: {list(changes.keys())}"
                    )
                    continue

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

    print("\n🚀 Iniciando sincronización de Clients")

    with get_session() as session:

        # Obtener items desde Podio
        client_service = podio_clients_router.get_service()
        items = client_service.get_items()
        print(f"📥 Recibidos {len(items)} items desde Podio (CLI)")

        for item in items:
            # ------------------------------------------------
            # ID del item en Podio
            # ------------------------------------------------
            podio_item_id = item.get("id") or item.get("item_id")
            if not podio_item_id:
                print(f"⚠️ Item sin ID encontrado, se omite: {item}")
                continue
            podio_item_id = str(podio_item_id)

            # Mapear item de Podio → dict listo para Client
            mapped = map_podio_item_to_client(item)

            # ------------------------------------------------
            # Buscar si ya existe por podio_item_id
            # ------------------------------------------------
            existing = session.exec(
                select(Client).where(Client.podio_item_id == podio_item_id)
            ).first()

            if existing:

                changes = {}
                for field, new_value in mapped.items():
                    old_value = getattr(existing, field, None)
                    if old_value != new_value and new_value is not None:
                        changes[field] = new_value
                if not changes:
                    print(
                        f"⚪ Item {existing.ID_Client} ya existe — sin cambios")
                    continue

                # Aplicar cambios
                for field, value in changes.items():
                    setattr(existing, field, value)
                print(
                    f"🟡 Actualizado {existing.ID_Client} → Campos cambiados: {list(changes.keys())}")

                continue

            else:  # Crear nuevo registro
                # ------------------------------------------------
                # Generar ID interno si no existe
                # ------------------------------------------------
                id_field = "ID_Client"
                Model = Client

                if not mapped.get(id_field):
                    prefix = "CLI"
                    new_id = generate_custom_id(
                        session, Model, id_field, prefix)
                    mapped[id_field] = str(new_id)
                    print(f"🆔 ID generado para Client: {mapped[id_field]}")
                else:
                    mapped[id_field] = str(mapped[id_field])

                try:
                    # También guardamos el podio_item_id
                    mapped["podio_item_id"] = podio_item_id
                    new_client = Client(**mapped)
                    session.add(new_client)
                    print(
                        f"🟢 Insertado: {mapped.get('Client_Community') or mapped.get('ID_Client')}")
                except Exception as e:
                    print(
                        f"❌ Error creando Client para podio_item_id={podio_item_id}: {e}")
                    continue

        # Guardar cambios
        session.commit()

    print("\n✅ Sincronización completa de TODOS los Clients.")


# ======================
#   SINCRONIZACIÓN TASKS
# ======================

@retry_db(max_retries=3, delay=1)
def sync_tasks():

    print("\n🚀 Iniciando sincronización de Tasks")

    with get_session() as session:

        # Obtener items desde Podio usando el router
        task_service = podio_tasks_router.get_service()
        items = task_service.get_items()
        print(f"📥 Recibidos {len(items)} items desde Podio (TASK)")

        for item in items:
            # ------------------------------------------------
            # ID del item en Podio
            # ------------------------------------------------
            podio_item_id = str(item.get("item_id") or item.get("id"))
            if not podio_item_id:
                print(f"⚠️ Task sin ID encontrado, se omite: {item}")
                continue

            # Mapear item de Podio → dict listo para Tasks
            mapped = map_podio_item_to_task(item, session)

            job_ref = mapped.get("ID_Jobs")
            print(f"Related Job: {job_ref}")

            # ------------------------------------------------
            # Buscar si ya existe por podio_item_id
            # ------------------------------------------------
            existing = session.exec(
                select(Tasks).where(Tasks.podio_item_id == podio_item_id)
            ).first()

            if existing:
                changes = {}
                for field, new_value in mapped.items():
                    old_value = getattr(existing, field, None)
                    if old_value != new_value and new_value is not None:
                        changes[field] = new_value
                if not changes:
                    print(
                        f"⚪ Item {existing.ID_Tasks} ya existe — sin cambios")
                    continue

                # Aplicar cambios
                for field, value in changes.items():
                    setattr(existing, field, value)
                print(
                    f"🟡 Actualizado {existing.ID_Tasks} → Campos cambiados: {list(changes.keys())}")

                continue

            else:  # Crear nuevo registro
                # ------------------------------------------------
                # Generar ID interno si no existe
                # ------------------------------------------------
                id_field = "ID_Tasks"  # Ajusta según tu modelo
                Model = Tasks

                if not mapped.get(id_field):
                    prefix = "TASK"
                    new_id = generate_custom_id(
                        session, Model, id_field, prefix)
                    mapped[id_field] = str(new_id)
                    print(f"🆔 ID generado para Task: {mapped[id_field]}")
                else:
                    mapped[id_field] = str(mapped[id_field])

                try:
                    mapped["podio_item_id"] = podio_item_id
                    new_task = Tasks(**mapped)
                    session.add(new_task)
                    print(
                        f"🟢 Insertado: {mapped.get('Name') or mapped.get('ID_Tasks')}")
                except Exception as e:
                    print(
                        f"❌ Error creando Task para podio_item_id={podio_item_id}: {e}")
                    continue

        session.commit()

    print("\n✅ Sincronización completa de TODAS las Tasks.")


# =========================
#  Punto de entrada global
# =========================

def sync_podio_to_db():
    print("🚀 Iniciando sincronización general desde Podio...")

    sync_clients()
    sync_jobs()
    sync_tasks()

    print("✅ Sincronización completa.")
