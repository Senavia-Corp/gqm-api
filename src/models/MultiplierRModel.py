
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .link_models.JobMultiplierR import JobMultiplierRLink


class MultiplierRBase(SQLModel):
    Start_value: Optional[float] = Field(default=None)
    End_value: Optional[float] = Field(default=None)
    Multiplier: Optional[float] = Field(default=None)


class MultiplierR(MultiplierRBase, table=True):
    __tablename__ = "multiplier_range"

    ID_MultiplierR: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones de muchos a muchos
    jobs: List["Job"] = Relationship(  # type: ignore
        back_populates="multipliers",
        link_model=JobMultiplierRLink
    )
