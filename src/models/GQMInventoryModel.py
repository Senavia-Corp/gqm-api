
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime


class InventoryBase(SQLModel):
    Equip_Name: Optional[str] = Field(default=None)
    Model: Optional[str] = Field(default=None)
    Cost: Optional[float] = Field(default=None)
    Serial_Number: Optional[str] = Field(default=None)
    Date_Purchase: Optional[datetime] = Field(default=None)
    Tag_ID: Optional[str] = Field(default=None)
    Internal_Notes: Optional[str] = Field(default=None)


class Inventory(InventoryBase, table=True):
    __tablename__ = "inventory"

    ID_Inventory: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas 1:M
    attachments: List["Attachments"] = Relationship(  # type: ignore
        back_populates="inventory",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})


class InventoryCreate(InventoryBase):
    pass


class InventoryUpdate(InventoryBase):
    pass
