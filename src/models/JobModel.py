
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from sqlalchemy import Column, TIMESTAMP, func
from datetime import datetime
from enum import Enum
from .ClientModel import Client
from .link_models.JobMember import JobMemberLink
from .MemberModel import Member
from .link_models.JobMultiplierR import JobMultiplierRLink
from .MultiplierRModel import MultiplierR
from .link_models.JobSubcontractor import JobSubcontractorLink
from .SubcontractorModel import Subcontractor


class JobType(str, Enum):
    QID = "QID"
    PTL = "PTL"
    PAR = "PAR"


class JobBase(SQLModel):

    Job_type: JobType
    Project_name: Optional[str] = Field(default=None)
    Project_location: Optional[str] = Field(default=None)
    Job_status: Optional[str] = Field(default=None)
    Po_wtn_wo: Optional[str] = Field(default=None)
    Service_type: Optional[str] = Field(default=None)
    Date_assigned: Optional[datetime] = Field(default_factory=datetime.now)
    Estimated_start_date: Optional[datetime] = Field(default=None)
    Estimated_project_duration: Optional[str] = Field(default=None)

    Gqm_formula_pricing: Optional[float] = Field(default=None)
    Gqm_adj_formula_pricing: Optional[float] = Field(default=None)
    Gqm_target_sold_pricing: Optional[float] = Field(default=None)
    Gqm_target_return: Optional[float] = Field(default=None)
    Gqm_premium_in_money: Optional[float] = Field(default=None)
    Gqm_final_sold_pricing: Optional[float] = Field(default=None)
    Gqm_final_percentage: Optional[float] = Field(default=None)
    Gqm_total_change_orders: Optional[float] = Field(default=None)

    client_podio_id: Optional[str] = Field(default=None)


class Job(JobBase, table=True):
    __tablename__ = "jobs"

    ID_Jobs: Optional[str] = Field(default=None, primary_key=True)

    # Referencias a Podio
    podio_item_id: Optional[str] = Field(
        default=None, index=True)

    # Relaciones foráneas M:1
    ID_Client: Optional[str] = Field(
        default=None, foreign_key="client.ID_Client")
    client: Optional["Client"] = Relationship(back_populates="jobs")

    # Relaciones foráneas 1:M
    attachments: List["Attachments"] = Relationship(  # type: ignore
        back_populates="job",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})
    tasks: List["Tasks"] = Relationship(  # type: ignore
        back_populates="job")
    estimate_costs: List["EstimateCost"] = Relationship(  # type: ignore
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
    subcontractors: List[Subcontractor] = Relationship(
        back_populates="jobs",
        link_model=JobSubcontractorLink
    )

    # Timestamps automáticos
    created_at: datetime = Field(
        sa_column=Column(TIMESTAMP(timezone=True),
                         server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(TIMESTAMP(timezone=True), server_default=func.now(
        ), onupdate=func.now(), nullable=False)
    )


class JobCreate(JobBase):
    ID_Client: Optional[str] = None


class JobUpdate(JobBase):
    ID_Client: Optional[str] = None
    Job_type: Optional[str] = None
