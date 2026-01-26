
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSON
from .link_models.JobSubcontractor import JobSubcontractorLink
from .RoleModel import Role
from .link_models.OpportunitiesLinks import OpportSubcLink
from .link_models.SkillsSubcontractor import SkillsSubcLink


class SubcontractorBase(SQLModel):
    Organization: Optional[str] = Field(default=None)
    Name: Optional[str] = Field(default=None)
    Email_Address: Optional[str] = Field(default=None)
    Phone_Number: Optional[str] = Field(default=None)
    Organization_Website: Optional[str] = Field(default=None)
    Address: Optional[str] = Field(default=None)
    Status: Optional[str] = Field(default=None)
    Score: Optional[float] = Field(default=None)
    Gqm_compliance: Optional[str] = Field(default=None)
    Gqm_best_service_training: Optional[str] = Field(default=None)
    Specialty: Optional[str] = Field(default=None)
    Coverage_Area: Optional[List[str]] = Field(
        default=None, sa_column=Column(JSON))
    Notes: Optional[str] = Field(default=None)


class Subcontractor(SubcontractorBase, table=True):
    __tablename__ = "subcontractor"

    ID_Subcontractor: Optional[str] = Field(default=None, primary_key=True)

    # Relación de muchos a muchos
    jobs: List["Job"] = Relationship(  # type: ignore
        back_populates="subcontractors",
        link_model=JobSubcontractorLink
    )
    opportunities: List["Opportunities"] = Relationship(  # type: ignore
        back_populates="subcontractors",
        link_model=OpportSubcLink
    )
    skills: List["Skills"] = Relationship(  # type: ignore
        back_populates="subcontractors",
        link_model=SkillsSubcLink
    )

    # Relaciones foráneas M:1
    ID_Role: Optional[str] = Field(
        default=None, foreign_key="role.ID_Role")
    role: Optional[Role] = Relationship(back_populates="subcontractors")

    # Relaciones foráneas 1:M
    technicians: List["Technician"] = Relationship(  # type: ignore
        back_populates="subcontractor")
    orders: List["Order"] = Relationship(  # type: ignore
        back_populates="subcontractor")
    attachments: List["Attachments"] = Relationship(  # type: ignore
        back_populates="subcontractor",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})
    tlactivity: List["TLActivity"] = Relationship(  # type: ignore
        back_populates="subcontractor",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})
    financial_docs: List["FinancialDocument"] = Relationship(  # type: ignore
        back_populates="subcontractor")


class SubcontractorCreate(SubcontractorBase):
    ID_Role: Optional[str] = None


class SubcontractorUpdate(SubcontractorBase):
    ID_Role: Optional[str] = None
