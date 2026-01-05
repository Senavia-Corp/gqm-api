
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .ParentMgmtCoModel import ParentMgmtCo
from .link_models.ClientPManager import ClientPrManagerLink
from .MemberModel import Member
from .link_models.ClientMember import ClientMemberLink

# ==================================== Modelos para PostgreSQL ====================================#


class ClientBase(SQLModel):
    Client_Community: Optional[str] = Field(default=None)
    Parent_Mgmt_Company: Optional[str] = Field(default=None)
    Address: Optional[str] = Field(default=None)
    Website: Optional[str] = Field(default=None)
    Invoice_Collection: Optional[str] = Field(default=None)
    Compliance_Partner: Optional[str] = Field(default=None)
    Risk_Value: Optional[str] = Field(default=None)
    Prop_Manager: Optional[str] = Field(default=None)
    Maintenance_Sup: Optional[str] = Field(default=None)
    Email_Address: Optional[str] = Field(default=None)
    Phone_Number: Optional[str] = Field(default=None)
    Client_Status: Optional[str] = Field(default=None)
    Services_interested_in: Optional[str] = Field(default=None)
    Text: Optional[str] = Field(default=None)


class Client(ClientBase, table=True):
    __tablename__ = "client"

    ID_Client: Optional[str] = Field(default=None, primary_key=True)

    # Referencias a Podio
    podio_item_id: Optional[str] = Field(
        default=None, index=True)

    # Relaciones foráneas 1:M
    jobs: List["Job"] = Relationship(back_populates="client")  # type: ignore

    # Relaciones foráneas M:1
    ID_Community_Tracking: Optional[str] = Field(
        default=None, foreign_key="parent_mgmt_co.ID_Community_Tracking")
    parent_mgmt_co: Optional["ParentMgmtCo"] = Relationship(
        back_populates="clients")

    # Relación de muchos a muchos
    property_manager: List["PropertyManager"] = Relationship(  # type: ignore
        back_populates="client",
        link_model=ClientPrManagerLink
    )
    members: List[Member] = Relationship(
        back_populates="clients",
        link_model=ClientMemberLink
    )


class ClientCreate(ClientBase):
    ID_Community_Tracking: Optional[str] = None


class ClientUpdate(ClientBase):
    ID_Community_Tracking: Optional[str] = None
