
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .MemberModel import Member


class CommissionBase(SQLModel):
    Month: Optional[str] = Field(default=None)
    Year: Optional[int] = Field(default=None)
    Total_commission: Optional[float] = Field(default=None)
    Total_margin: Optional[float] = Field(default=None)
    Total_reimbursment: Optional[float] = Field(default=None)


class Commission(CommissionBase, table=True):
    __tablename__ = "commission"

    ID_Commission: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas M:1
    ID_Member: Optional[str] = Field(
        default=None, foreign_key="member.ID_Member")
    member: Optional[Member] = Relationship(back_populates="commissions")

    # Relaciones foráneas 1:M
    comgroups: List["CommissionGroup"] = Relationship(  # type: ignore
        back_populates="commission",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})


class CommissionCreate(CommissionBase):
    ID_Member: Optional[str] = None


class CommissionUpdate(CommissionBase):
    ID_Member: Optional[str] = None
