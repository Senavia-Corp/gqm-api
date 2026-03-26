# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .CommissionModel import Commission


class CommissionGrBase(SQLModel):
    Jobs_type: Optional[str] = Field(default=None)
    Jobs_year: Optional[int] = Field(default=None)
    Rol: Optional[str] = Field(default=None)
    Total_detail: Optional[float] = Field(default=None)


class CommissionGroup(CommissionGrBase, table=True):
    __tablename__ = "commission_group"

    ID_ComGroup: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas M:1
    ID_Commission: Optional[str] = Field(
        default=None, foreign_key="commission.ID_Commission")
    commission: Optional[Commission] = Relationship(back_populates="comgroups")

    # Relaciones foráneas 1:M
    comdetails: List["CommissionDetail"] = Relationship(  # type: ignore
        back_populates="comgroup",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})


class CommissionGrCreate(CommissionGrBase):
    ID_Commission: Optional[str] = None


class CommissionGrUpdate(CommissionGrBase):
    ID_Commission: Optional[str] = None
