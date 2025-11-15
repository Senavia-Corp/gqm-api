
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field
from typing import Optional


class SubcontractorBase(SQLModel):
    Organization: str
    Name: Optional[str] = Field(default=None)
    Email_Address: str
    Phone_Number: Optional[str] = Field(default=None)
    Organization_Website: Optional[str] = Field(default=None)
    Address: Optional[str] = Field(default=None)
    State: str
    Score: Optional[float] = Field(default=None)
    Gqm_compliance: Optional[str] = Field(default=None)
    Gqm_best_service_training: Optional[str] = Field(default=None)


class Subcontractor(SubcontractorBase, table=True):
    __tablename__ = "subcontractor"

    ID_Subcontractor: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas
    # ID_Rol: Optional[str] = Field(default=None, foreign_key="rol.ID_Rol")
    # rol: Optional["Rol"] = Relationship()


class SubcontractorCreate(SubcontractorBase):
    pass
    # ID_Rol: Optional[str] = None


class SubcontractorUpdate(SubcontractorBase):
    # ID_Rol: Optional[str] = None
    Organization: Optional[str] = Field(default=None)
    Email_Address: Optional[str] = Field(default=None)
    State: Optional[str] = Field(default=None)
