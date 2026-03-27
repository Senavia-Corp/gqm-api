
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from .CommissionModel import Commission


class ReimbursementBase(SQLModel):
    Reference: Optional[str] = Field(default=None)
    Value: Optional[float] = Field(default=None)


class Reimbursement(ReimbursementBase, table=True):
    __tablename__ = "reimbursement"

    ID_Reimbursement: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas M:1
    ID_Commission: Optional[str] = Field(
        default=None, foreign_key="commission.ID_Commission")
    commission: Optional[Commission] = Relationship(
        back_populates="reimbursements")


class ReimbursementCreate(ReimbursementBase):
    ID_Commission: Optional[str] = None


class ReimbursementUpdate(ReimbursementBase):
    ID_Commission: Optional[str] = None
