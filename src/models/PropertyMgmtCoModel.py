
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List

# ==================================== Modelos para PostgreSQL ====================================#


class PrMgmtCoBase(SQLModel):
    Property_mgmt_co: Optional[str] = Field(default=None)
    Main_office_hq: Optional[str] = Field(default=None)
    Main_office_email: Optional[str] = Field(default=None)
    Main_office_number: Optional[str] = Field(default=None)
    State: Optional[str] = Field(default=None)


class PropertyMgmtCo(PrMgmtCoBase, table=True):
    __tablename__ = "property_mgmt_co"

    ID_Community_Tracking: Optional[str] = Field(
        default=None, primary_key=True)

    # Relaciones foráneas 1:M
    clients: List["Client"] = Relationship(  # type: ignore
        back_populates="property_mgmt_co")
    property_managers: List["PropertyManager"] = Relationship(  # type: ignore
        back_populates="property_mgmt_co")


class PrMgmtCoCreate(PrMgmtCoBase):
    pass


class PrMgmtCoUpdate(PrMgmtCoBase):
    pass
