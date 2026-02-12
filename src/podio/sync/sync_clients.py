from sqlmodel import select
from src.database.db_sqlmodel import get_session
from src.utils.middleware.retries.retries import retry_db
from src.utils.id_generator import generate_custom_id
from src.podio.services.client_services import podio_clients_router
from src.utils.mappers.from_podio.client_mapper import map_podio_item_to_client
from src.models.ClientModel import Client
from src.models.ParentMgmtCoModel import ParentMgmtCo
from src.models.MemberModel import Member
from src.models.link_models.ClientLinks import ClientMemberLink
from src.utils.mappers.podio_relationships import get_related_app_ids, get_contact_profile_ids, get_text_values_by_external_id
from src.utils.mappers.from_podio.client_manager_relationship import get_or_create_manager_by_name, link_client_manager


# ===============================
# ----------- FASE 1 -----------
# ===============================

# SYNC Clients
@retry_db(max_retries=3, delay=1)
def sync_clients(limit: int = 30, offset: int = 0, dry_run: bool = False):
    """
    Sincronzación de Clients desde Podio a PostgreSQL.
    - Batch pequeño
    - Offset manual
    - Dry-run opcional
    """

    service = podio_clients_router.get_service()
    items = service.get_items(limit=limit, offset=offset)

    print(f"📥 Clients recibidos: {len(items)} | offset={offset}")

    if not items:
        print("✅ No hay más registros.")
        return {"processed": 0}

    created = 0
    updated = 0

    with get_session() as session:
        for item in items:
            mapped = map_podio_item_to_client(item)
            podio_item_id = mapped["podio_item_id"]

            existing = session.exec(
                select(Client).where(Client.podio_item_id == podio_item_id)
            ).first()

            if existing:
                changes = {
                    k: v for k, v in mapped.items()
                    if getattr(existing, k) != v
                }

                if changes:
                    updated += 1
                    if not dry_run:
                        for k, v in changes.items():
                            setattr(existing, k, v)

            else:
                created += 1
                if not dry_run:
                    new_id = generate_custom_id(
                        session, Client, "ID_Client", "CLI"
                    )
                    mapped["ID_Client"] = new_id
                    session.add(Client(**mapped))

        if not dry_run:
            session.commit()

    return {
        "processed": len(items),
        "created": created,
        "updated": updated,
        "limit": limit,
        "offset": offset,
        "dry_run": dry_run
    }


# ===============================
# ----------- FASE 2 -----------
# ===============================

# SYNC relaciones de Clients tipo APP
@retry_db(max_retries=3, delay=1)
def sync_client_related_apps(limit: int = 30, offset: int = 0, dry_run: bool = False):
    """
    Sincroniza relaciones tipo APP de Clients ya existentes.
    """

    service = podio_clients_router.get_service()
    items = service.get_items(limit=limit, offset=offset)

    print(f"🔗 Clients (APP relations): {len(items)} | offset={offset}")

    if not items:
        print("✅ No hay más registros.")
        return {"processed": 0}

    updated = 0

    with get_session() as session:
        for item in items:

            fields = item.get("fields", [])
            podio_item_id = str(item.get("item_id"))

            client = session.exec(
                select(Client).where(Client.podio_item_id == podio_item_id)
            ).first()

            if not client:
                print(f"⚠️ Client {podio_item_id} no existe en DB")
                continue

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
                updated += 1
                if not dry_run:
                    client.ID_Community_Tracking = new_value
                    session.add(client)

        if not dry_run:
            session.commit()

    return {
        "processed": len(items),
        "updated": updated,
        "limit": limit,
        "offset": offset,
        "dry_run": dry_run
    }


# SYNC relaciones de Clients tipo CONTACT
@retry_db(max_retries=3, delay=1)
def sync_client_related_contacts(
    limit: int = 30,
    offset: int = 0,
    dry_run: bool = False
):
    """
    Sincroniza relaciones tipo CONTACT (Client ↔ Member) con rol.
    """

    service = podio_clients_router.get_service()
    items = service.get_items(limit=limit, offset=offset)

    print(f"👥 Clients (CONTACT relations): {len(items)} | offset={offset}")

    if not items:
        print("✅ No hay más registros.")
        return {"processed": 0}

    updated = 0
    created = 0

    # mapa external_id → rol
    contact_roles = {
        "acc-rep": "Acc. Rep",
        "inv-acc-pro": "Inv/Acc Pro"
    }

    with get_session() as session:
        for item in items:

            fields = item.get("fields", [])
            podio_item_id = str(item.get("item_id"))

            client = session.exec(
                select(Client).where(Client.podio_item_id == podio_item_id)
            ).first()

            if not client:
                print(f"⚠️ Client {podio_item_id} no existe en DB")
                continue

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
                        print(
                            f"⚠️ Member con profile_id {profile_id} no existe")
                        continue

                    link = session.exec(
                        select(ClientMemberLink).where(
                            ClientMemberLink.clients_id == client.ID_Client,
                            ClientMemberLink.members_id == member.ID_Member
                        )
                    ).first()

                    if link:
                        if link.rol != rol:
                            updated += 1
                            if not dry_run:
                                link.rol = rol
                                session.add(link)
                        continue

                    created += 1
                    if not dry_run:
                        session.add(
                            ClientMemberLink(
                                clients_id=client.ID_Client,
                                members_id=member.ID_Member,
                                rol=rol
                            )
                        )

        if not dry_run:
            session.commit()

    return {
        "processed": len(items),
        "created": created,
        "updated": updated,
        "limit": limit,
        "offset": offset,
        "dry_run": dry_run
    }


# SYNC relaciones y creación de Managers
MANAGER_FIELDS = {
    "contact-name": "Property Manager",
    "maintenance-sup": "Maintenance / Sup",
    "regional-manager": "Regional Manager",
}


@retry_db(max_retries=3, delay=1)
def sync_client_related_managers(
    limit: int = 30,
    offset: int = 0,
    dry_run: bool = False
):
    service = podio_clients_router.get_service()
    items = service.get_items(limit=limit, offset=offset)

    processed = 0

    with get_session() as session:
        for item in items:
            fields = item.get("fields", [])
            podio_item_id = str(item.get("item_id"))

            client = session.exec(
                select(Client).where(
                    Client.podio_item_id == podio_item_id
                )
            ).first()

            if not client:
                continue

            for external_id, rol in MANAGER_FIELDS.items():
                names = get_text_values_by_external_id(
                    fields, external_id
                )

                for name in names:
                    manager = get_or_create_manager_by_name(
                        session, name
                    )

                    if not dry_run:
                        link_client_manager(
                            session,
                            client.ID_Client,
                            manager.ID_Manager,
                            rol
                        )

            processed += 1

        if not dry_run:
            session.commit()

    return {
        "processed": processed,
        "limit": limit,
        "offset": offset,
        "dry_run": dry_run
    }
