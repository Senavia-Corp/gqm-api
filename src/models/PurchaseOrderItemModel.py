
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .PurchaseOrderModel import PurchaseOrder


class POrderItemBase(SQLModel):
    Name: Optional[str] = Field(default=None)
    Quote_shop: Optional[str] = Field(default=None)
    Quote_link: Optional[str] = Field(default=None)
    Quote_value: Optional[float] = Field(default=None)
    Quote_notes: Optional[str] = Field(default=None)
    Purchase_shop: Optional[str] = Field(default=None)
    Purchase_link: Optional[str] = Field(default=None)
    Purchase_value: Optional[float] = Field(default=None)
    Purchase_notes: Optional[str] = Field(default=None)


class PurchaseOrderItem(POrderItemBase, table=True):
    __tablename__ = "purchase_order_item"

    ID_PurchaseOrderItem: Optional[str] = Field(default=None, primary_key=True)

    # Referencias a Podio
    podio_item_id: Optional[str] = Field(
        default=None, index=True)

    # Relaciones foráneas M:1
    ID_PurchaseOrder: Optional[str] = Field(
        default=None, foreign_key="purchase_order.ID_PurchaseOrder")
    purchase_order: Optional[PurchaseOrder] = Relationship(
        back_populates="porder_items")


class POrderItemCreate(POrderItemBase):
    ID_PurchaseOrder: Optional[str] = None


class POrderItemUpdate(POrderItemBase):
    ID_PurchaseOrder: Optional[str] = None
