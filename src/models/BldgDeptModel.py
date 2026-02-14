
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from sqlalchemy import Column, JSON


class BldgDeptBase(SQLModel):
    City_BldgDept: Optional[str] = Field(default=None)
    Location: Optional[str] = Field(default=None)
    Office_Email: Optional[list] = Field(default=None, sa_column=Column(JSON))
    Portal_Log_In: Optional[str] = Field(default=None)
    PW: Optional[str] = Field(default=None)
    Phone: Optional[list] = Field(default=None, sa_column=Column(JSON))
    Link: Optional[str] = Field(default=None)
    Notes_Inspectors: Optional[str] = Field(default=None)


class BuildingDept(BldgDeptBase, table=True):
    __tablename__ = "bldg_dept"

    ID_BldgDept: Optional[str] = Field(default=None, primary_key=True)

    # Referencias a Podio
    podio_item_id: Optional[str] = Field(
        default=None, index=True)

    # Relaciones foráneas 1:M
    jobs: List["Job"] = Relationship(  # type: ignore
        back_populates="building_dept")


class BuildingDeptCreate(BldgDeptBase):
    pass


class BuildingDeptUpdate(BldgDeptBase):
    pass
