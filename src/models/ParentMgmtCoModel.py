
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List

# ==================================== Modelos para PostgreSQL ====================================#


class PaMgmtCoBase(SQLModel):
    Property_mgmt_co: Optional[str] = Field(default=None)
    Company_abbrev: Optional[str] = Field(default=None)
    Main_office_hq: Optional[str] = Field(default=None)
    Main_office_email: Optional[str] = Field(default=None)
    Main_office_number: Optional[str] = Field(default=None)
    State: Optional[str] = Field(default=None)


class ParentMgmtCo(PaMgmtCoBase, table=True):
    __tablename__ = "parent_mgmt_co"

    ID_Community_Tracking: Optional[str] = Field(
        default=None, primary_key=True)

    # Referencias a Podio
    podio_item_id: Optional[str] = Field(
        default=None, index=True)

    # Relaciones foráneas 1:M
    clients: List["Client"] = Relationship(  # type: ignore
        back_populates="parent_mgmt_co")
    managers: List["Manager"] = Relationship(  # type: ignore
        back_populates="parent_mgmt_co")
    tlactivity: List["TLActivity"] = Relationship(  # type: ignore
        back_populates="parent_mgmt_co",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})


class PaMgmtCoCreate(PaMgmtCoBase):
    pass


class PaMgmtCoUpdate(PaMgmtCoBase):
    pass
