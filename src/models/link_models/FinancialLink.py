from sqlmodel import SQLModel, Field


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
