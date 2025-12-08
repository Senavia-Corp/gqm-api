# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .JobModel import Job
from .TechnicianModel import Technician
from datetime import date


class TasksBase(SQLModel):
    Task_description: Optional[str] = Field(default=None)
    Task_status: Optional[str] = Field(default=None)
    Designation_date: Optional[date] = Field(default_factory=date.today)
    Delivery_date: Optional[date] = Field(default_factory=date.today)
    Priority: Optional[str] = Field(default=None)
    Name: Optional[str] = Field(default=None)

    job_podio_id: Optional[str] = Field(default=None)


class Tasks(TasksBase, table=True):
    __tablename__ = "tasks"

    ID_Tasks: Optional[str] = Field(default=None, primary_key=True)

    # Referencias a Podio
    podio_item_id: Optional[str] = Field(
        default=None, index=True)

    # Relaciones foráneas M:1
    ID_Jobs: Optional[str] = Field(
        default=None, foreign_key="jobs.ID_Jobs")
    job: Optional[Job] = Relationship(back_populates="tasks")

    ID_Technician: Optional[str] = Field(
        default=None, foreign_key="technician.ID_Technician")
    technician: Optional[Technician] = Relationship(back_populates="tasks")


class TasksCreate(TasksBase):
    ID_Jobs: Optional[str] = None
    ID_Technician: Optional[str] = None


class TasksUpdate(TasksBase):
    ID_Jobs: Optional[str] = None
    ID_Technician: Optional[str] = None
