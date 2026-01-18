from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import date
from enum import Enum
from .FinancialTransModel import FinancialTransaction
from .link_models.FinancialLink import FinancialLink
from .ClientModel import Client
from .JobModel import Job
from .OrderModel import Order
from .SubcontractorModel import Subcontractor


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


class FinancialDocument(FDocBase, table=True):
    __tablename__ = "financial_document"

    ID_FinancialDoc: Optional[str] = Field(default=None, primary_key=True)

    # Referencias a QBO
    qbo_id: Optional[str] = Field(default=None)

    #  Relaciones foráneas 1:M
    financial_doc_items: List["FinancialDoc_Item"] = Relationship(  # type: ignore
        back_populates="financial_document")

    # Relación de muchos a muchos
    financial_transactions: List[FinancialTransaction] = Relationship(
        back_populates="financial_documents",
        link_model=FinancialLink
    )

    # Relaciones foráneas M:1
    ID_Client: Optional[str] = Field(
        default=None, foreign_key="client.ID_Client")
    client: Optional["Client"] = Relationship(back_populates="financial_docs")
    ID_Jobs: Optional[str] = Field(
        default=None, foreign_key="jobs.ID_Jobs")
    job: Optional[Job] = Relationship(back_populates="financial_docs")
    ID_Order: Optional[str] = Field(
        default=None, foreign_key="order.ID_Order")
    order: Optional["Order"] = Relationship(back_populates="financial_docs")
    ID_Subcontractor: Optional[str] = Field(
        default=None, foreign_key="subcontractor.ID_Subcontractor")
    subcontractor: Optional[Subcontractor] = Relationship(
        back_populates="financial_docs")


class FDocCreate(FDocBase):
    ID_Client: Optional[str] = None
    ID_Jobs: Optional[str] = None
    ID_Order: Optional[str] = None
    ID_Subcontractor: Optional[str] = None


class FDocUpdate(FDocBase):
    Type_of_document: Optional[str] = None
    ID_Client: Optional[str] = None
    ID_Jobs: Optional[str] = None
    ID_Order: Optional[str] = None
    ID_Subcontractor: Optional[str] = None
