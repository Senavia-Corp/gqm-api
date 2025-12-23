from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime
from .SubcontractorModel import Subcontractor
from .link_models.JobPaymentU import JobPaymentULink

# ==================================== Modelos para PostgreSQL ====================================#


class PaymentUBase(SQLModel):
    Total_amount_paid: Optional[float] = Field(default=None)
    Description_payment: Optional[str] = Field(default=None)
    Percentage_paid: Optional[float] = Field(default=None)
    Percentage_remaining_to_pay: Optional[float] = Field(default=None)
    Type_of_payment: Optional[str] = Field(default=None)
    Date: Optional[datetime] = Field(default=None)


class PaymentUnit(PaymentUBase, table=True):
    __tablename__ = "payment_unit"

    ID_PaymentU: Optional[str] = Field(default=None, primary_key=True)

    # Relación de muchos a muchos
    jobs: List["Job"] = Relationship(  # type: ignore
        back_populates="payment_units",
        link_model=JobPaymentULink
    )

    # Relaciones foráneas M:1
    ID_Subcontractor: Optional[str] = Field(
        default=None, foreign_key="subcontractor.ID_Subcontractor")
    subcontractor: Optional[Subcontractor] = Relationship(
        back_populates="payment_units")


class PaymentUCreate(PaymentUBase):
    ID_Subcontractor: Optional[str] = None


class PaymentUUpdate(PaymentUBase):
    ID_Subcontractor: Optional[str] = None
