from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime
from .JobModel import Job
from .SubcontractorModel import Subcontractor
from .SkillsModel import Skills
from .link_models.OpportunitiesLinks import OpportSubcLink, OpportSkillsLink

# ==================================== Modelos para PostgreSQL ====================================#


class OpportBase(SQLModel):
    Project_name: Optional[str] = Field(default=None)
    Description: Optional[str] = Field(default=None)
    State: Optional[bool] = Field(default=None)
    Priority: Optional[str] = Field(default=None)
    Start_Date: Optional[datetime] = Field(default=None)


class Opportunities(OpportBase, table=True):
    __tablename__ = "opportunities"

    ID_Opportunities: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas M:1
    ID_Jobs: Optional[str] = Field(
        default=None, foreign_key="jobs.ID_Jobs")
    job: Optional[Job] = Relationship(back_populates="opportunities")

    # Relación con Order (M:1) — la order que se les pagará a los subcontratistas
    ID_Order: Optional[str] = Field(
        default=None, foreign_key="order.ID_Order")
    order: Optional["Order"] = Relationship(back_populates="opportunities")  # type: ignore

    # Relaciones de muchos a muchos
    skills: List[Skills] = Relationship(
        back_populates="opportunities",
        link_model=OpportSkillsLink
    )
    subcontractors: List[Subcontractor] = Relationship(
        back_populates="opportunities",
        link_model=OpportSubcLink
    )


class OpportunitiesCreate(OpportBase):
    ID_Jobs: Optional[str] = None
    ID_Order: Optional[str] = None


class OpportunitiesUpdate(OpportBase):
    ID_Jobs: Optional[str] = None
    ID_Order: Optional[str] = None

