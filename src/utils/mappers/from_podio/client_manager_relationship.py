from sqlmodel import select
from src.utils.id_generator import generate_custom_id
from src.models.ManagerModel import Manager
from src.models.link_models.ClientLinks import ClientManagerLink


# Obtener o crear manager
def get_or_create_manager_by_name(
    session,
    name: str
) -> Manager:
    """
    Busca un Manager por nombre (case-insensitive).
    Si no existe, lo crea.
    """
    clean_name = name.strip()

    manager = session.exec(
        select(Manager).where(
            Manager.Manager_name.ilike(clean_name)
        )
    ).first()

    if manager:
        return manager

    new_id = generate_custom_id(
        session, Manager, "ID_Manager", "MNG"
    )

    manager = Manager(
        ID_Manager=new_id,
        Manager_name=clean_name
    )

    session.add(manager)
    session.flush()  # importante para usar el ID luego

    return manager


# Crear link entre manager y client
def link_client_manager(
    session,
    client_id: str,
    manager_id: str,
    rol: str
):
    """
    Crea relación Client_Manager si no existe.
    """
    exists = session.exec(
        select(ClientManagerLink).where(
            ClientManagerLink.clients_id == client_id,
            ClientManagerLink.manager_id == manager_id,
            ClientManagerLink.rol == rol
        )
    ).first()

    if exists:
        return

    session.add(
        ClientManagerLink(
            clients_id=client_id,
            manager_id=manager_id,
            rol=rol
        )
    )
