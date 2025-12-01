
from sqlmodel import SQLModel, Field


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
