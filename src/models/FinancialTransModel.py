from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import date, datetime
from enum import Enum
from .link_models.FinancialLink import FinancialLink
from sqlalchemy import Column, TIMESTAMP, func

# ==================================== Modelos para PostgreSQL ====================================#


class TransactionType(str, Enum):
    Bill_payments = "Bill Payment"
    Invoice_payments = "Invoice Payment"


class FTransBase(SQLModel):
    Type_of_transaction: TransactionType
    Reference_number: Optional[str] = Field(default=None)
    Total_Amount: Optional[float] = Field(default=None)
    Bank_Account_Ref: Optional[str] = Field(default=None)
    Type_of_payment: Optional[str] = Field(default=None)
    Date_of_payment: Optional[date] = Field(default=None)
    is_emailed: Optional[bool] = Field(default=None)
    is_voided: Optional[bool] = Field(default=None)


class FinancialTransaction(FTransBase, table=True):
    __tablename__ = "financial_transaction"

    ID_FTransaction: Optional[str] = Field(default=None, primary_key=True)

    # Referencias a QBO
    qbo_id: Optional[str] = Field(default=None, unique=True, index=True)

    # Relación de muchos a muchos
    financial_documents: List["FinancialDocument"] = Relationship(  # type: ignore
        back_populates="financial_transactions",
        link_model=FinancialLink
    )

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

class FTransactionCreate(FTransBase):
    pass


class FTransactionUpdate(FTransBase):
    Type_of_transaction: Optional[str] = None
