
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List

# ==================================== Modelos para PostgreSQL ====================================#


class ClientBase(SQLModel):
    Client_Community: str
    Parent_Mgmt_Company: str
    Parent_Company: str
    Address: str
    Website: Optional[str] = Field(default=None)
    Invoice_Collection: Optional[str] = Field(default=None)
    Compliance_Partner: Optional[str] = Field(default=None)
    Risk_Value: Optional[str] = Field(default=None)
    Prop_Manager: str
    Email_Address: str
    Phone_Number: str
    Client_Status: str
    Services_interested_in: Optional[str] = Field(default=None)


class Client(ClientBase, table=True):
    __tablename__ = "client"

    ID_Client: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas 1:M
    jobs: List["Job"] = Relationship(back_populates="client")  # type: ignore

    # ID_Community_Tracking: Optional[str] = Field(default=None, foreign_key="property_mgmt_co.ID_Community_Tracking")
    # ID_PropertyManager: Optional[str] = Field(default=None, foreign_key="property_manager.ID_PropertyManager")


class ClientCreate(ClientBase):
    pass


class ClientUpdate(ClientBase):
    Client_Community: Optional[str] = Field(default=None)
    Parent_Mgmt_Company: Optional[str] = Field(default=None)
    Parent_Company: Optional[str] = Field(default=None)
    Address: Optional[str] = Field(default=None)
    Prop_Manager: Optional[str] = Field(default=None)
    Email_Address: Optional[str] = Field(default=None)
    Phone_Number: Optional[str] = Field(default=None)
    Client_Status: Optional[str] = Field(default=None)
