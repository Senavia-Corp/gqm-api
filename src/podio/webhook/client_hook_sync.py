from sqlmodel import select
from src.utils.id_generator import generate_custom_id
from src.utils.mappers.from_podio.client_mapper import map_podio_item_to_client
from src.models.ClientModel import Client
from src.models.ParentMgmtCoModel import ParentMgmtCo
from src.models.MemberModel import Member
from src.models.link_models.ClientLinks import ClientMemberLink
from src.utils.mappers.podio_relationships import get_related_app_ids, get_contact_profile_ids, get_text_values_by_external_id
from src.utils.mappers.from_podio.client_manager_relationship import get_or_create_manager_by_name, link_client_manager


def upsert_client_from_item(session, item):
    mapped = map_podio_item_to_client(item)
    podio_item_id = mapped["podio_item_id"]

    existing = session.exec(
        select(Client).where(Client.podio_item_id == podio_item_id)
    ).first()

    if existing:
        target = existing

    else:
        new_id = generate_custom_id(
            session, Client, "ID_Client", "CLI")
        mapped["ID_Client"] = new_id
        target = Client(**mapped)

    for k, v in mapped.items():
        if k != "ID_Client":
            setattr(target, k, v)

    session.add(target)
    return target


def add_client_app_relations(session, client, item):
    fields = item.get("fields", [])

    # 🔗 Client → Parent Mgmt Co (APP)
    related_ids = get_related_app_ids(
        fields=fields,
        external_id="relationship",  # external_id en Podio
        session=session,
        model=ParentMgmtCo,
        podio_field="podio_item_id",
        internal_id_field="ID_Community_Tracking"
    )

    new_value = related_ids[0] if related_ids else None

    if client.ID_Community_Tracking != new_value:
        client.ID_Community_Tracking = new_value
        session.add(client)


def add_client_contact_relations(session, client, item):
    fields = item.get("fields", [])

    contact_roles = {
        "acc-rep": "Acc. Rep",
        "inv-acc-pro": "Inv/Acc Pro"
    }

    for external_id, rol in contact_roles.items():

        profile_ids = get_contact_profile_ids(
            fields=fields,
            external_id=external_id
        )

        for profile_id in profile_ids:

            member = session.exec(
                select(Member).where(
                    Member.podio_profile_id == profile_id
                )
            ).first()

            if not member:
                print(f"⚠️ Member con profile_id {profile_id} no existe")
                continue

            link = session.exec(
                select(ClientMemberLink).where(
                    ClientMemberLink.clients_id == client.ID_Client,
                    ClientMemberLink.members_id == member.ID_Member
                )
            ).first()

            # 🔄 Si ya existe el link
            if link:
                if link.rol != rol:
                    link.rol = rol
                    session.add(link)
                continue

            # ➕ Crear nuevo link
            session.add(
                ClientMemberLink(
                    clients_id=client.ID_Client,
                    members_id=member.ID_Member,
                    rol=rol
                )
            )


def add_client_manager_relations(session, client, item):
    # SYNC relaciones y creación de Managers
    MANAGER_FIELDS = {
        "contact-name": "Property Manager",
        "maintenance-sup": "Maintenance / Sup",
        "regional-manager": "Regional Manager",
    }

    fields = item.get("fields", [])

    for external_id, rol in MANAGER_FIELDS.items():

        names = get_text_values_by_external_id(
            fields,
            external_id
        )

        for name in names:
            if not name:
                continue

            manager = get_or_create_manager_by_name(
                session,
                name
            )

            link_client_manager(
                session,
                client.ID_Client,
                manager.ID_Manager,
                rol
            )


# -------- FUNCIÓN PARA UNIFICAR CLIENT FASE 1 Y 2
def process_clients_podio(session, item):
    client = upsert_client_from_item(session, item)

    if not client:
        return

    add_client_app_relations(session, client, item)
    add_client_contact_relations(session, client, item)
    add_client_manager_relations(session, client, item)
