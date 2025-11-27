
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import date
from enum import Enum
from .ClientModel import Client
from .link_models.JobMember import JobMemberLink
from .MemberModel import Member
from .link_models.JobMultiplierR import JobMultiplierRLink
from .MultiplierRModel import MultiplierR


class JobType(str, Enum):
    QID = "QID"
    PTL = "PTL"
    PAR = "PAR"


class JobBase(SQLModel):

    Job_type: JobType
    Project_name: str
    Project_location: str
    Job_status: str
    Po_wtn_wo: Optional[str] = Field(default=None)
    Service_type: Optional[str] = Field(default=None)
    Date_assigned: Optional[date] = Field(default=date.today)
    Estimated_start_date: Optional[date] = Field(default=None)
    Estimated_project_duration: Optional[str] = Field(default=None)

    Gqm_formula_pricing: Optional[float] = Field(default=None)
    Gqm_adj_formula_pricing: Optional[float] = Field(default=None)
    Gqm_target_sold_pricing: Optional[float] = Field(default=None)
    Gqm_target_return: Optional[float] = Field(default=None)
    Gqm_premium_in_money: Optional[float] = Field(default=None)
    Gqm_final_sold_pricing: Optional[float] = Field(default=None)
    # Gqm_final_sold_pricing: float
    Gqm_final_percentage: Optional[float] = Field(default=None)
    Gqm_total_change_orders: Optional[float] = Field(default=None)


class Job(JobBase, table=True):
    __tablename__ = "jobs"

    ID_Jobs: Optional[str] = Field(default=None, primary_key=True)
    podio_item_id: Optional[str] = Field(
        default=None, index=True)  # referencia a Podio

    # Relaciones foráneas 1:M
    ID_Client: Optional[str] = Field(
        default=None, foreign_key="client.ID_Client")
    client: Optional["Client"] = Relationship(back_populates="jobs")

    attachments: List["Attachments"] = Relationship(  # type: ignore
        back_populates="job")

    # Relaciones de muchos a muchos
    multipliers: List[MultiplierR] = Relationship(
        back_populates="jobs",
        link_model=JobMultiplierRLink
    )
    members: List[Member] = Relationship(
        back_populates="jobs",
        link_model=JobMemberLink
    )


class JobCreate(JobBase):
    ID_Client: Optional[str] = None


class JobUpdate(SQLModel):

    ID_Client: Optional[str] = None
    Project_name: Optional[str] = Field(default=None)
    Project_location: Optional[str] = Field(default=None)
    Job_status: Optional[str] = Field(default=None)
    Po_wtn_wo: Optional[str] = Field(default=None)
    Service_type: Optional[str] = Field(default=None)
    Date_assigned: Optional[str] = Field(default=None)
    Estimated_start_date: Optional[date] = Field(default=None)
    Estimated_project_duration: Optional[str] = Field(default=None)

    Gqm_formula_pricing: Optional[float] = Field(default=None)
    Gqm_adj_formula_pricing: Optional[float] = Field(default=None)
    Gqm_target_sold_pricing: Optional[float] = Field(default=None)
    Gqm_target_return: Optional[float] = Field(default=None)
    Gqm_premium_in_money: Optional[float] = Field(default=None)
    Gqm_final_sold_pricing: Optional[float] = Field(default=None)
    Gqm_final_percentage: Optional[float] = Field(default=None)
    Gqm_total_change_orders: Optional[float] = Field(default=None)
