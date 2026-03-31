from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from datetime import datetime
from .JobModel import Job
from .TechnicianModel import Technician
from .MemberModel import Member
from .SubcontractorModel import Subcontractor
from .ClientModel import Client
from .ParentMgmtCoModel import ParentMgmtCo

# ==================================== Modelos para PostgreSQL ====================================#


class TLActivityBase(SQLModel):
    Action: Optional[str] = Field(default=None)
    Action_datetime: Optional[datetime] = Field(default_factory=datetime.now)
    Description: Optional[str] = Field(default=None)


class TLActivity(TLActivityBase, table=True):
    __tablename__ = "tlactivity"

    ID_TLActivity: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas M:1
    ID_Jobs: Optional[str] = Field(
        default=None, foreign_key="jobs.ID_Jobs")
    job: Optional[Job] = Relationship(back_populates="tlactivity")
    ID_Member: Optional[str] = Field(
        default=None, foreign_key="member.ID_Member")
    member: Optional[Member] = Relationship(back_populates="tlactivity")
    ID_Technician: Optional[str] = Field(
        default=None, foreign_key="technician.ID_Technician")
    technician: Optional[Technician] = Relationship(
        back_populates="tlactivity")
    ID_Subcontractor: Optional[str] = Field(
        default=None, foreign_key="subcontractor.ID_Subcontractor")
    subcontractor: Optional[Subcontractor] = Relationship(
        back_populates="tlactivity")
    ID_Client: Optional[str] = Field(
        default=None, foreign_key="client.ID_Client")
    client: Optional[Client] = Relationship(
        back_populates="tlactivity")
    ID_Community_Tracking: Optional[str] = Field(
        default=None, foreign_key="parent_mgmt_co.ID_Community_Tracking")
    parent_mgmt_co: Optional[ParentMgmtCo] = Relationship(
        back_populates="tlactivity")


class TLActivityCreate(TLActivityBase):
    ID_Jobs: Optional[str] = None
    ID_Member: Optional[str] = None
    ID_Technician: Optional[str] = None
    ID_Subcontractor: Optional[str] = None
    ID_Client: Optional[str] = None
    ID_Community_Tracking: Optional[str] = None


class TLActivityUpdate(TLActivityBase):
    ID_Jobs: Optional[str] = None
    ID_Member: Optional[str] = None
    ID_Technician: Optional[str] = None
    ID_Subcontractor: Optional[str] = None
    ID_Client: Optional[str] = None
    ID_Community_Tracking: Optional[str] = None
