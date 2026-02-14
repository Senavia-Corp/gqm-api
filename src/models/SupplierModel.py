
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .link_models.PurchaseSupplier import PurchaseSupplierLink


class SupplierBase(SQLModel):

    Company_Name: Optional[str] = Field(default=None)
    Company_Website: Optional[str] = Field(default=None)
    Description: Optional[str] = Field(default=None)
    Acc_Status: Optional[str] = Field(default=None)
    Acc_Rep: Optional[str] = Field(default=None)
    Speciality: Optional[str] = Field(default=None)
    Email_Address: Optional[str] = Field(default=None)
    Coverage_Area: Optional[str] = Field(default=None)
    Phone_Number: Optional[str] = Field(default=None)
    Address: Optional[str] = Field(default=None)


class Supplier(SupplierBase, table=True):
    __tablename__ = "supplier"

    ID_Supplier: Optional[str] = Field(default=None, primary_key=True)

    # Referencias a Podio
    podio_item_id: Optional[str] = Field(
        default=None, index=True)

    # Relaciones foráneas 1:M
    attachments: List["Attachments"] = Relationship(  # type: ignore
        back_populates="supplier",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})

    # Relación de muchos a muchos
    purchases: List["Purchase"] = Relationship(  # type: ignore
        back_populates="suppliers",
        link_model=PurchaseSupplierLink
    )


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(SupplierBase):
    pass
