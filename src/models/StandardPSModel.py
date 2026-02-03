from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from .ClientModel import Client

# ==================================== Modelos para PostgreSQL ====================================#


class StandardPSBase(SQLModel):
    Item_name: Optional[str] = Field(default=None)
    Quantity: Optional[float] = Field(default=None)
    Unit_price: Optional[float] = Field(default=None)
    Price: Optional[float] = Field(default=None)
    Category: Optional[str] = Field(default=None)


class StandardPS(StandardPSBase, table=True):
    __tablename__ = "standard_ps"

    ID_StandardPS: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas M:1
    ID_Client: Optional[str] = Field(
        default=None, foreign_key="client.ID_Client")
    client: Optional[Client] = Relationship(
        back_populates="standard_ps")


class StandardPSCreate(StandardPSBase):
    ID_Client: Optional[str] = None


class StandardPSUpdate(StandardPSBase):
    ID_Client: Optional[str] = None
