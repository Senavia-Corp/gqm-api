from sqlmodel import SQLModel, Field
from typing import Optional


# Tabla intermedia con GQM Member
class ClientMemberLink(SQLModel, table=True):
    __tablename__ = "client_member"

    clients_id: str = Field(
        foreign_key="client.ID_Client",
        primary_key=True
    )

    members_id: str = Field(
        foreign_key="member.ID_Member",
        primary_key=True
    )

    rol: Optional[str] = Field(default=None)


# Tabla intermedia con Property Manager
class ClientPrManagerLink(SQLModel, table=True):
    __tablename__ = "client_property_manager"

    clients_id: str = Field(
        foreign_key="client.ID_Client",
        primary_key=True
    )

    property_manager_id: str = Field(
        foreign_key="property_manager.ID_PropertyManager",
        primary_key=True
    )
