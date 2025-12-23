
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSON
from .link_models.JobSubcontractor import JobSubcontractorLink


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

    # Relaciones foráneas 1:M
    technicians: List["Technician"] = Relationship(  # type: ignore
        back_populates="subcontractor")
    orders: List["Order"] = Relationship(  # type: ignore
        back_populates="subcontractor")
    attachments: List["Attachments"] = Relationship(  # type: ignore
        back_populates="subcontractor",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})
    payment_units: List["PaymentUnit"] = Relationship(  # type: ignore
        back_populates="subcontractor")


class SubcontractorCreate(SubcontractorBase):
    pass
    # ID_Rol: Optional[str] = None


class SubcontractorUpdate(SubcontractorBase):
    pass
    # ID_Rol: Optional[str] = None
