
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from sqlalchemy import Column, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import JSON
from datetime import datetime
from enum import Enum
from .ClientModel import Client
from .link_models.JobMember import JobMemberLink
from .MemberModel import Member
from .link_models.JobMultiplierR import JobMultiplierRLink
from .MultiplierRModel import MultiplierR
from .link_models.JobSubcontractor import JobSubcontractorLink
from .SubcontractorModel import Subcontractor
from .link_models.JobPaymentU import JobPaymentULink
from .PaymentUnitModel import PaymentUnit
from .BldgDeptModel import BuildingDept


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
    Date_assigned: Optional[datetime] = Field(default=None)
    Date_assigned_end: Optional[datetime] = Field(default=None)
    Estimated_start_date: Optional[datetime] = Field(default=None)
    Estimated_start_date_end: Optional[datetime] = Field(default=None)
    Estimated_project_duration: Optional[str] = Field(default=None)
    Date_Received: Optional[datetime] = Field(default=None)
    Estimated_completion_date: Optional[datetime] = Field(default=None)
    Additional_detail: Optional[str] = Field(default=None)

    Estimated_rent: Optional[float] = Field(default=None)
    Estimated_material: Optional[float] = Field(default=None)
    Estimated_city: Optional[float] = Field(default=None)

    Tech_formula_pricing: Optional[float] = Field(default=None)
    Gqm_formula_pricing: Optional[float] = Field(default=None)
    Gqm_adj_formula_pricing: Optional[float] = Field(default=None)
    Gqm_target_sold_pricing: Optional[float] = Field(default=None)
    Gqm_target_return: Optional[float] = Field(default=None)
    Gqm_premium_in_money: Optional[float] = Field(default=None)
    Gqm_final_sold_pricing: Optional[float] = Field(default=None)
    Gqm_final_percentage: Optional[float] = Field(default=None)

    Pricing_target: Optional[str] = Field(default=None)
    Permit: Optional[str] = Field(default=None)
    Gqm_total_change_orders: Optional[float] = Field(default=None)
    Gqm_total_materials_fees: Optional[float] = Field(default=None)

    Acc_receivable: Optional[float] = Field(default=None)
    Gqm_final_form_pricing: Optional[float] = Field(default=None)
    Gqm_final_adj_form_pricing: Optional[float] = Field(default=None)
    Gqm_final_target_return: Optional[float] = Field(default=None)
    Gqm_final_prem_in_money: Optional[float] = Field(default=None)

    Ptl_Superintendent: Optional[str] = Field(default=None)
    Ptl_property_id: Optional[str] = Field(default=None)
    Ptl_gc_fee: Optional[float] = Field(default=None)

    Gqm_paid_fees: Optional[float] = Field(default=None)
    Bldg_dept_fees: Optional[List[Optional[float]]] = Field(
        default=None, sa_column=Column(JSON))


class Job(JobBase, table=True):
    __tablename__ = "jobs"

    ID_Jobs: Optional[str] = Field(default=None, primary_key=True)

    # Referencias a Podio
    podio_item_id: Optional[str] = Field(
        default=None, index=True)

    # Relaciones foráneas M:1
    ID_Client: Optional[str] = Field(
        default=None, foreign_key="client.ID_Client")
    client: Optional[Client] = Relationship(back_populates="jobs")
    ID_BldgDept: Optional[str] = Field(
        default=None, foreign_key="bldg_dept.ID_BldgDept")
    building_dept: Optional[BuildingDept] = Relationship(back_populates="jobs")

    # Relaciones foráneas 1:M
    attachments: List["Attachments"] = Relationship(  # type: ignore
        back_populates="job",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})
    tasks: List["Tasks"] = Relationship(  # type: ignore
        back_populates="job")
    estimate_costs: List["EstimateCost"] = Relationship(  # type: ignore
        back_populates="job",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})
    tlactivity: List["TLActivity"] = Relationship(  # type: ignore
        back_populates="job",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})
    opportunities: List["Opportunities"] = Relationship(  # type: ignore
        back_populates="job")
    change_orders: List["ChangeOrder"] = Relationship(  # type: ignore
        back_populates="job")
    financial_docs: List["FinancialDocument"] = Relationship(  # type: ignore
        back_populates="job")
    purchases: List["Purchase"] = Relationship(  # type: ignore
        back_populates="job")
    chat_messages: List["ChatMessage"] = Relationship(  # type: ignore
        back_populates="job",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})
    comdetails: List["CommissionDetail"] = Relationship(  # type: ignore
        back_populates="job",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})

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
    payment_units: List[PaymentUnit] = Relationship(
        back_populates="jobs",
        link_model=JobPaymentULink
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
    ID_BldgDept: Optional[str] = None


class JobUpdate(JobBase):
    ID_Client: Optional[str] = None
    ID_BldgDept: Optional[str] = None
    Job_type: Optional[str] = None
