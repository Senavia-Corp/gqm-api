
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .SubcontractorModel import Subcontractor


class TechnicianBase(SQLModel):
    Name: Optional[str] = Field(default=None)
    Location: Optional[str] = Field(default=None)
    Email_Address: str
    Phone_Number: Optional[str] = Field(default=None)
    Type_of_technician: Optional[str] = Field(default=None)
    Password: str


class Technician(TechnicianBase, table=True):
    __tablename__ = "technician"

    ID_Technician: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas M:1
    ID_Subcontractor: Optional[str] = Field(
        default=None, foreign_key="subcontractor.ID_Subcontractor")
    subcontractor: Optional["Subcontractor"] = Relationship(
        back_populates="technicians")

    # Relaciones foráneas 1:M
    tasks: List["Tasks"] = Relationship(  # type: ignore
        back_populates="technician")


class TechnicianCreate (TechnicianBase):
    ID_Subcontractor: Optional[str] = None


class TechnicianUpdate(SQLModel):
    ID_Subcontractor: Optional[str] = None
    Name: Optional[str] = Field(default=None)
    Location: Optional[str] = Field(default=None)
    Email_Address: Optional[str] = Field(default=None)
    Phone_Number: Optional[str] = Field(default=None)
    Type_of_technician: Optional[str] = Field(default=None)
    Password: Optional[str] = Field(default=None)
