
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .SubcontractorModel import Subcontractor
from .link_models.OpportunitiesLinks import OpportSkillsLink
from .link_models.SkillsSubcontractor import SkillsSubcLink


class SkillsBase(SQLModel):
    Skill_name: Optional[str] = Field(default=None)
    Division_trade: Optional[str] = Field(default=None)


class Skills(SkillsBase, table=True):
    __tablename__ = "skills"

    ID_Skill: Optional[str] = Field(default=None, primary_key=True)

    # Relación de muchos a muchos
    opportunities: List["Opportunities"] = Relationship(  # type: ignore
        back_populates="skills",
        link_model=OpportSkillsLink
    )
    subcontractors: List[Subcontractor] = Relationship(
        back_populates="skills",
        link_model=SkillsSubcLink
    )


class SkillsCreate(SkillsBase):
    pass


class SkillsUpdate(SkillsBase):
    pass
