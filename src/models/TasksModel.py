# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from .JobModel import Job
from .TechnicianModel import Technician
from .MemberModel import Member
from .SubcontractorModel import Subcontractor
from datetime import date

from pydantic import field_validator, model_validator


class TasksBase(SQLModel):
    Task_description: Optional[str] = Field(default=None)
    Task_status: Optional[str] = Field(default=None)
    Designation_date: Optional[date] = Field(default_factory=date.today)
    Delivery_date: Optional[date] = Field(default_factory=date.today)
    Priority: Optional[str] = Field(default=None)
    Name: Optional[str] = Field(default=None)


class Tasks(TasksBase, table=True):
    __tablename__ = "tasks"

    ID_Tasks: Optional[str] = Field(default=None, primary_key=True)

    # Referencias a Podio
    podio_item_id: Optional[str] = Field(
        default=None, index=True)

    # Relaciones foráneas M:1
    ID_Jobs: Optional[str] = Field(
        default=None, foreign_key="jobs.ID_Jobs", ondelete="CASCADE")
    job: Optional[Job] = Relationship(back_populates="tasks")
    ID_Technician: Optional[str] = Field(
        default=None, foreign_key="technician.ID_Technician")
    technician: Optional[Technician] = Relationship(back_populates="tasks")
    ID_Member: Optional[str] = Field(
        default=None, foreign_key="member.ID_Member")
    member: Optional[Member] = Relationship(back_populates="tasks")
    ID_Subcontractor: Optional[str] = Field(
        default=None, foreign_key="subcontractor.ID_Subcontractor")
    subcontractor: Optional[Subcontractor] = Relationship(back_populates="tasks")


# T-01/T-02/T-04/T-07 — vocabulario canónico. Antes eran strings libres, así que
# la página del portal escribía "Not Started"/"In Progress" y esas tareas
# quedaban invisibles en el kanban (que filtra por igualdad exacta).
ESTADOS = ("Not started", "Work-in-progress", "Completed")
PRIORIDADES = ("High", "Medium", "Low")


class _ValidacionTasks(SQLModel):
    """Reglas comunes a crear y actualizar (aprobadas en la Fase 1 de la auditoría)."""

    @field_validator("Task_status", check_fields=False)
    @classmethod
    def _estado_valido(cls, v):
        if v is not None and v not in ESTADOS:
            raise ValueError(f"Task_status debe ser uno de {ESTADOS}, no {v!r}")
        return v

    @field_validator("Priority", check_fields=False)
    @classmethod
    def _prioridad_valida(cls, v):
        if v is not None and v not in PRIORIDADES:
            raise ValueError(f"Priority debe ser una de {PRIORIDADES}, no {v!r}")
        return v

    @model_validator(mode="after")
    def _fechas_coherentes(self):
        if (self.Delivery_date and self.Designation_date
                and self.Delivery_date < self.Designation_date):
            raise ValueError(
                "Delivery_date no puede ser anterior a Designation_date "
                f"({self.Delivery_date} < {self.Designation_date})")
        return self


class TasksCreate(TasksBase, _ValidacionTasks):
    ID_Jobs: Optional[str] = None
    ID_Technician: Optional[str] = None
    ID_Member: Optional[str] = None
    ID_Subcontractor: Optional[str] = None

    @field_validator("Name", check_fields=False)
    @classmethod
    def _nombre_obligatorio(cls, v):
        if v is None or not str(v).strip():
            raise ValueError("Name es obligatorio")
        return str(v).strip()

    @model_validator(mode="after")
    def _debe_colgar_de_algo(self):
        # R4: la tarea automática de certificado NO lleva job por diseño, lleva
        # subcontratista. Por eso la regla es «job O subcontratista», nunca
        # «job obligatorio» a secas: eso rompería esa automatización.
        if not self.ID_Jobs and not self.ID_Subcontractor:
            raise ValueError(
                "La tarea debe llevar ID_Jobs o ID_Subcontractor")
        return self


class TasksUpdate(TasksBase, _ValidacionTasks):
    ID_Jobs: Optional[str] = None
    ID_Technician: Optional[str] = None
    ID_Member: Optional[str] = None
    ID_Subcontractor: Optional[str] = None
