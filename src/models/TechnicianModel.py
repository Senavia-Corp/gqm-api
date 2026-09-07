
# ==================================== Modelos para PostgreSQL ====================================#

from pydantic import field_validator

from src.utils.validacion_correo import validar_formato_correo
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .SubcontractorModel import Subcontractor
from .link_models.PermissionLinks import PermissionTechLink
from .link_models.JobTechnician import JobTechnicianLink


class TechnicianBase(SQLModel):
    Name: Optional[str] = Field(default=None)
    Location: Optional[str] = Field(default=None)
    Email_Address: str
    Phone_Number: Optional[str] = Field(default=None)
    Type_of_technician: Optional[str] = Field(default=None)
    Password: str


    # El formato del correo, que es el nombre de usuario de acceso.
    # Va en la Base para que lo hereden los esquemas Create/Update, que
    # es por donde entran las escrituras HTTP. El modelo de tabla
    # (`table=True`) NO ejecuta validadores, asi que los datos que ya
    # estan en la BD se siguen leyendo sin problema.
    _validar_correo = field_validator('Email_Address')(validar_formato_correo)

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
    attachments: List["Attachments"] = Relationship(  # type: ignore
        back_populates="technician",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})
    tlactivity: List["TLActivity"] = Relationship(  # type: ignore
        back_populates="technician",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})

    # Relación de muchos a muchos
    permissions: List["Permission"] = Relationship(  # type: ignore
        back_populates="technicians",
        link_model=PermissionTechLink
    )
    jobs: List["Job"] = Relationship(  # type: ignore
        back_populates="technicians",
        link_model=JobTechnicianLink
    )


class TechnicianCreate (TechnicianBase):
    ID_Subcontractor: Optional[str] = None


class TechnicianUpdate(TechnicianBase):
    ID_Subcontractor: Optional[str] = None
    Email_Address: Optional[str] = Field(default=None)
    Password: Optional[str] = Field(default=None)
