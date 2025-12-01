
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field
from typing import Optional


class SkillsBase(SQLModel):
    Skill_name: Optional[str] = Field(default=None)
    Division_trade: Optional[str] = Field(default=None)


class Skills(SkillsBase, table=True):
    __tablename__ = "skills"

    ID_Skill: Optional[str] = Field(default=None, primary_key=True)
