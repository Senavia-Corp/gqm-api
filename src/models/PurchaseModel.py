
# ==================================== Modelos para PostgreSQL ====================================#

from sqlalchemy import Column, TIMESTAMP, func
from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .MemberModel import Member
from .JobModel import Job
from .link_models.PurchaseSupplier import PurchaseSupplierLink


class PurchaseBase(SQLModel):
    Selling_rep: Optional[str] = Field(default=None)
    Description: Optional[str] = Field(default=None)
    PickUp_person: Optional[str] = Field(default=None)
    Delivery_location: Optional[str] = Field(default=None)
    Status: Optional[str] = Field(default=None)
    Return_request: Optional[str] = Field(default=None)
    Return_status: Optional[str] = Field(default=None)
    Total_spending: Optional[float] = Field(default=None)


class Purchase(PurchaseBase, table=True):
    __tablename__ = "purchase"

    ID_Purchase: Optional[str] = Field(default=None, primary_key=True)

    # Referencias a Podio
    podio_item_id: Optional[str] = Field(
        default=None, index=True)

    # Relaciones foráneas M:1
    ID_Jobs: Optional[str] = Field(
        default=None, foreign_key="jobs.ID_Jobs")
    job: Optional[Job] = Relationship(back_populates="purchases")
    ID_Member: Optional[str] = Field(
        default=None, foreign_key="member.ID_Member")
    member: Optional[Member] = Relationship(back_populates="purchases")

    # Relaciones foráneas 1:M
    purchase_orders: List["PurchaseOrder"] = Relationship(  # type: ignore
        back_populates="purchase")

    # Relación de muchos a muchos
    suppliers: List["Supplier"] = Relationship(  # type: ignore
        back_populates="purchases",
        link_model=PurchaseSupplierLink
    )

    # Timestamps automáticos
    created_at: datetime = Field(
        sa_column=Column(TIMESTAMP(timezone=True),
                         server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(TIMESTAMP(timezone=True), server_default=func.now(
        ), onupdate=func.now(), nullable=False)
    )


class PurchaseCreate(PurchaseBase):
    ID_Jobs: Optional[str] = None
    ID_Member: Optional[str] = None


class PurchaseUpdate(PurchaseBase):
    ID_Jobs: Optional[str] = None
    ID_Member: Optional[str] = None
