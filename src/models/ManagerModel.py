
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .ParentMgmtCoModel import ParentMgmtCo
from .link_models.ClientLinks import ClientManagerLink
from .ClientModel import Client

# ==================================== Modelos para PostgreSQL ====================================#


class ManagerBase(SQLModel):
    Manager_name: Optional[str] = Field(default=None)
    Manager_email: Optional[str] = Field(default=None)
    Manager_location: Optional[str] = Field(default=None)


class Manager(ManagerBase, table=True):
    __tablename__ = "manager"

    ID_Manager: Optional[str] = Field(
        default=None, primary_key=True)

    # Relación foráneas M:1
    ID_Community_Tracking: Optional[str] = Field(
        default=None, foreign_key="parent_mgmt_co.ID_Community_Tracking")
    parent_mgmt_co: Optional["ParentMgmtCo"] = Relationship(
        back_populates="managers")

    # Relación de muchos a muchos
    client: List[Client] = Relationship(
        back_populates="manager",
        link_model=ClientManagerLink
    )


class ManagerCreate(ManagerBase):
    ID_Community_Tracking: Optional[str] = None


class ManagerUpdate(ManagerBase):
    ID_Community_Tracking: Optional[str] = None
