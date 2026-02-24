from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .FinancialDocModel import FinancialDocument


# ==================================== Modelos para PostgreSQL ====================================#

class FDItemBase(SQLModel):
    Name: Optional[str] = Field(default=None)
    Description: Optional[str] = Field(default=None)
    Unit_price: Optional[float] = Field(default=None)
    Quantity: Optional[float] = Field(default=None)
    Amount: Optional[float] = Field(default=None)


class FinancialDoc_Item(FDItemBase, table=True):
    __tablename__ = "financial_doc_item"

    ID_FDItem: Optional[str] = Field(default=None, primary_key=True)

    # Referencias a QBO
    qbo_line_id: Optional[str] = Field(default=None)

    # Relaciones foráneas M:1
    ID_FinancialDoc: Optional[str] = Field(
        default=None, foreign_key="financial_document.ID_FinancialDoc")
    financial_document: Optional[FinancialDocument] = Relationship(
        back_populates="financial_doc_items")


class FDItemCreate(FDItemBase):
    ID_FinancialDoc: Optional[str] = None


class FDItemUpdate(FDItemBase):
    ID_FinancialDoc: Optional[str] = None
