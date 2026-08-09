from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import date, datetime
from sqlalchemy import Column, TIMESTAMP, func


class FinancialLink(SQLModel, table=True):
    __tablename__ = "fdocument_ftransaction"

    fdocument_id: str = Field(
        foreign_key="financial_document.ID_FinancialDoc",
        primary_key=True
    )

    ftransaction_id: str = Field(
        foreign_key="financial_transaction.ID_FTransaction",
        primary_key=True
    )
    amount_applied: Optional[float] = Field(default=None)
    date_applied: Optional[date] = Field(default=None)

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
