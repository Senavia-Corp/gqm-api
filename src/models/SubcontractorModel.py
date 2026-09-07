
# ==================================== Modelos para PostgreSQL ====================================#

from pydantic import field_validator

from src.utils.validacion_correo import validar_formato_correo
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSON
from .link_models.JobSubcontractor import JobSubcontractorLink
from .RoleModel import Role
from .link_models.OpportunitiesLinks import OpportSubcLink
from .link_models.SkillsSubcontractor import SkillsSubcLink
from .link_models.PermissionLinks import PermissionSubcLink


class SubcontractorBase(SQLModel):
    Organization: Optional[str] = Field(default=None)
    Name: Optional[str] = Field(default=None)
    Email_Address: Optional[str] = Field(default=None)
    Phone_Number: Optional[str] = Field(default=None)
    Organization_Website: Optional[str] = Field(default=None)
    Address: Optional[str] = Field(default=None)
    Status: Optional[str] = Field(default=None)
    Score: Optional[float] = Field(default=None)
    Gqm_compliance: Optional[str] = Field(default=None)
    Gqm_best_service_training: Optional[str] = Field(default=None)
    Specialty: Optional[str] = Field(default=None)
    Coverage_Area: Optional[List[str]] = Field(
        default=None, sa_column=Column(JSON))
    Notes: Optional[str] = Field(default=None)
    Password: Optional[str] = Field(default=None)


    # El formato del correo, que es el nombre de usuario de acceso.
    # Va en la Base para que lo hereden los esquemas Create/Update, que
    # es por donde entran las escrituras HTTP. El modelo de tabla
    # (`table=True`) NO ejecuta validadores, asi que los datos que ya
    # estan en la BD se siguen leyendo sin problema.
    _validar_correo = field_validator('Email_Address')(validar_formato_correo)

class Subcontractor(SubcontractorBase, table=True):
    __tablename__ = "subcontractor"

    ID_Subcontractor: Optional[str] = Field(default=None, primary_key=True)

    # Referencias a Podio
    podio_item_id: Optional[str] = Field(
        default=None, index=True)

    # Relación de muchos a muchos
    jobs: List["Job"] = Relationship(  # type: ignore
        back_populates="subcontractors",
        link_model=JobSubcontractorLink
    )
    opportunities: List["Opportunities"] = Relationship(  # type: ignore
        back_populates="subcontractors",
        link_model=OpportSubcLink
    )
    skills: List["Skills"] = Relationship(  # type: ignore
        back_populates="subcontractors",
        link_model=SkillsSubcLink
    )
    permissions: List["Permission"] = Relationship(  # type: ignore
        back_populates="subcontractors",
        link_model=PermissionSubcLink
    )

    # Relaciones foráneas M:1
    ID_Role: Optional[str] = Field(
        default=None, foreign_key="role.ID_Role")
    role: Optional[Role] = Relationship(back_populates="subcontractors")

    # Relaciones foráneas 1:M
    technicians: List["Technician"] = Relationship(  # type: ignore
        back_populates="subcontractor")
    tasks: List["Tasks"] = Relationship(  # type: ignore
        back_populates="subcontractor")
    orders: List["Order"] = Relationship(  # type: ignore
        back_populates="subcontractor")
    attachments: List["Attachments"] = Relationship(  # type: ignore
        back_populates="subcontractor",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})
    tlactivity: List["TLActivity"] = Relationship(  # type: ignore
        back_populates="subcontractor",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})
    certificates: List["Certificate"] = Relationship(  # type: ignore
        back_populates="subcontractor",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})


class SubcontractorCreate(SubcontractorBase):
    ID_Role: Optional[str] = None


class SubcontractorUpdate(SubcontractorBase):
    ID_Role: Optional[str] = None
    Password: Optional[str] = Field(default=None)
