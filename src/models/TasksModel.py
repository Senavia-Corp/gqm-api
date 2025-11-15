# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import date


class TasksBase(SQLModel):
    Task_description: Optional[str] = Field(default=None)
    Task_status: Optional[str] = Field(default=None)
    Designation_date: Optional[date] = Field(default_factory=date.today)
    Delivery_date: Optional[date] = Field(default_factory=date.today)


class Tasks(TasksBase, table=True):
    __tablename__ = "tasks"

    ID_Tasks: Optional[str] = Field(default=None, primary_key=True)
    ID_Jobs: Optional[str] = Field(default=None, foreign_key="jobs.ID_Jobs")
    ID_Subcontractor: Optional[str] = Field(
        default=None, foreign_key="subcontractor.ID_Subcontractor")


class TasksCreate(TasksBase):
    pass


class TasksUpdate(TasksBase):
    pass
