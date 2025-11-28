
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .PropertyMgmtCoModel import PropertyMgmtCo
from .link_models.ClientPManager import ClientPrManagerLink
from .ClientModel import Client

# ==================================== Modelos para PostgreSQL ====================================#


class PropertyManagerBase(SQLModel):
    Manager_name: Optional[str] = Field(default=None)
    Manager_email: Optional[str] = Field(default=None)
    Manager_location: Optional[str] = Field(default=None)


class PropertyManager(PropertyManagerBase, table=True):
    __tablename__ = "property_manager"

    ID_PropertyManager: Optional[str] = Field(
        default=None, primary_key=True)

    # Relación foráneas M:1
    ID_Community_Tracking: Optional[str] = Field(
        default=None, foreign_key="property_mgmt_co.ID_Community_Tracking")
    property_mgmt_co: Optional["PropertyMgmtCo"] = Relationship(
        back_populates="property_managers")

    # Relación de muchos a muchos
    client: List[Client] = Relationship(
        back_populates="property_manager",
        link_model=ClientPrManagerLink
    )


class PrManagerCreate(PropertyManagerBase):
    ID_Community_Tracking: Optional[str] = None


class PrManagerUpdate(PropertyManagerBase):
    ID_Community_Tracking: Optional[str] = None
