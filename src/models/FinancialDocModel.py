from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import date, datetime
from enum import Enum
from .FinancialTransModel import FinancialTransaction
from .link_models.FinancialLink import FinancialLink
from .JobModel import Job
from .OrderModel import Order
from sqlalchemy import Column, TIMESTAMP, func


# ==================================== Modelos para PostgreSQL ====================================#

class DocumentType(str, Enum):
    Bill = "Bill"
    Invoice = "Invoice"


class FDocBase (SQLModel):
    Type_of_document: DocumentType
    Job_Ref_QBO: Optional[str] = Field(default=None)
    Total_Amount: Optional[float] = Field(default=None)
    Balance_Amount: Optional[float] = Field(default=None)
    Percentage_Paid: Optional[float] = Field(default=None)
    Notes: Optional[str] = Field(default=None)
    Due_Date: Optional[date] = Field(default=None)
    is_emailed: Optional[bool] = Field(default=None)
    is_voided: Optional[bool] = Field(default=None)
    Vendor_Customer: Optional[str] = Field(default=None)


class FinancialDocument(FDocBase, table=True):
    __tablename__ = "financial_document"

    ID_FinancialDoc: Optional[str] = Field(default=None, primary_key=True)

    # Referencias a QBO
    qbo_id: Optional[str] = Field(default=None, unique=True, index=True)

    #  Relaciones foráneas 1:M
    financial_doc_items: List["FinancialDoc_Item"] = Relationship(  # type: ignore
        back_populates="financial_document",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})
    attachments: List["Attachments"] = Relationship(  # type: ignore
        back_populates="financial_document",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})

    # Relación de muchos a muchos
    financial_transactions: List[FinancialTransaction] = Relationship(
        back_populates="financial_documents",
        link_model=FinancialLink
    )

    # Relaciones foráneas M:1
    ID_Jobs: Optional[str] = Field(
        default=None, foreign_key="jobs.ID_Jobs")
    job: Optional[Job] = Relationship(back_populates="financial_docs")
    ID_Order: Optional[str] = Field(
        default=None, foreign_key="order.ID_Order")
    order: Optional[Order] = Relationship(back_populates="financial_docs")

    # Timestamps automáticos (REG-042/REG-101)
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True),
                         server_default=func.now(), nullable=False)
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True), server_default=func.now(),
                         onupdate=func.now(), nullable=False)
    )

class FDocCreate(FDocBase):
    ID_Jobs: Optional[str] = None
    ID_Order: Optional[str] = None


class FDocUpdate(FDocBase):
    Type_of_document: Optional[str] = None
    ID_Jobs: Optional[str] = None
    ID_Order: Optional[str] = None
