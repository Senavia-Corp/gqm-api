from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from .JobModel import Job

# ==================================== Modelos para PostgreSQL ====================================#


class ChangeOrBase(SQLModel):
    Name: Optional[str] = Field(default=None)
    Description: Optional[str] = Field(default=None)
    ChangeOrderFormula: Optional[float] = Field(default=None)
    State: Optional[str] = Field(default=None)


class ChangeOrder(ChangeOrBase, table=True):
    __tablename__ = "change_order"

    ID_ChangeOrder: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas M:1
    ID_Jobs: Optional[str] = Field(
        default=None, foreign_key="jobs.ID_Jobs")
    job: Optional[Job] = Relationship(back_populates="change_orders")


class ChangeOrCreate(ChangeOrBase):
    ID_Jobs: Optional[str] = None


class ChangeOrUpdate(ChangeOrBase):
    ID_Jobs: Optional[str] = None
