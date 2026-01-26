from sqlmodel import SQLModel, Field
from typing import Optional


# Tabla intermedia con Subcontractor
class SkillsSubcLink(SQLModel, table=True):
    __tablename__ = "skills_subcontractors"

    subcon_id: str = Field(
        foreign_key="subcontractor.ID_Subcontractor",
        primary_key=True
    )

    skills_id: str = Field(
        foreign_key="skills.ID_Skill",
        primary_key=True
    )

    Certificated: Optional[bool] = Field(default=None)
