from sqlmodel import SQLModel, Field
from typing import Optional


# Tabla intermedia con Skills
class OpportSkillsLink(SQLModel, table=True):
    __tablename__ = "opportunities_skills"

    opport_id: str = Field(
        foreign_key="opportunities.ID_Opportunities",
        primary_key=True
    )

    skills_id: str = Field(
        foreign_key="skills.ID_Skill",
        primary_key=True
    )


# Tabla intermedia con Subcontractor
class OpportSubcLink(SQLModel, table=True):
    __tablename__ = "opportunities_subcontractors"

    opport_id: str = Field(
        foreign_key="opportunities.ID_Opportunities",
        primary_key=True
    )

    subcon_id: str = Field(
        foreign_key="subcontractor.ID_Subcontractor",
        primary_key=True
    )

    State: Optional[str] = Field(default=None)
