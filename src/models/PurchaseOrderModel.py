
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime
from .PurchaseModel import Purchase


class PurchaseOrderBase(SQLModel):
    Order_title: Optional[str] = Field(default=None)
    Est_delivery_date: Optional[datetime] = Field(default=None)
    Order_confirmation: Optional[bool] = Field(default=None)


class PurchaseOrder(PurchaseOrderBase, table=True):
    __tablename__ = "purchase_order"

    ID_PurchaseOrder: Optional[str] = Field(default=None, primary_key=True)

    # Referencias a Podio
    podio_item_id: Optional[str] = Field(
        default=None, index=True)

    # Relaciones foráneas M:1
    ID_Purchase: Optional[str] = Field(
        default=None, foreign_key="purchase.ID_Purchase")
    purchase: Optional[Purchase] = Relationship(
        back_populates="purchase_orders")

    # Relaciones foráneas 1:M
    porder_items: List["PurchaseOrderItem"] = Relationship(  # type: ignore
        back_populates="purchase_order")


class POrderCreate(PurchaseOrderBase):
    ID_Purchase: Optional[str] = None


class POrderUpdate(PurchaseOrderBase):
    ID_Purchase: Optional[str] = None
