# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from .ComGroupModel import CommissionGroup
from .JobModel import Job


class CommissionDeBase(SQLModel):
    Factor: Optional[float] = Field(default=None)
    Sell_Mgmt: Optional[float] = Field(default=None)


class CommissionDetail(CommissionDeBase, table=True):
    __tablename__ = "commission_detail"

    ID_ComDetail: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas M:1
    ID_ComGroup: Optional[str] = Field(
        default=None, foreign_key="commission_group.ID_ComGroup")
    comgroup: Optional[CommissionGroup] = Relationship(
        back_populates="comdetails")

    ID_Jobs: Optional[str] = Field(
        default=None, foreign_key="jobs.ID_Jobs")
    job: Optional[Job] = Relationship(back_populates="comdetails")


class CommissionDeCreate(CommissionDeBase):
    ID_ComGroup: Optional[str] = None
    ID_Jobs: Optional[str] = None


class CommissionDeUpdate(CommissionDeBase):
    ID_ComGroup: Optional[str] = None
    ID_Jobs: Optional[str] = None
