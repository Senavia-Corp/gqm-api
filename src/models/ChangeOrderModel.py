from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from .JobModel import Job
from .OrderModel import Order
from datetime import datetime
from sqlalchemy import Column, TIMESTAMP, func

# ==================================== Modelos para PostgreSQL ====================================#


class ChangeOrBase(SQLModel):
    Name: Optional[str] = Field(default=None)
    Description: Optional[str] = Field(default=None)
    ChangeOrderFormula: Optional[float] = Field(default=None)
    State: Optional[str] = Field(default=None)
    # Para guardar el external id de donde viene (TECH x - Change Order o CHANGE ORDER)
    podio_field: Optional[str] = Field(default=None)


class ChangeOrder(ChangeOrBase, table=True):
    __tablename__ = "change_order"

    ID_ChangeOrder: Optional[str] = Field(default=None, primary_key=True)

    # Para poder conectar con Podio si se hacen modificaciones
    job_podio_id: Optional[str] = Field(default=None)

    # Relaciones foráneas M:1
    ID_Jobs: Optional[str] = Field(
        default=None, foreign_key="jobs.ID_Jobs")
    job: Optional[Job] = Relationship(back_populates="change_orders")
    ID_Order: Optional[str] = Field(
        default=None, foreign_key="order.ID_Order")
    order: Optional[Order] = Relationship(back_populates="change_orders")

    # Timestamps automáticos (REG-042/REG-101)
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True),
                         server_default=func.now(), nullable=False)
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True), server_default=func.now(),
                         onupdate=func.now(), nullable=False)
    )

class ChangeOrCreate(ChangeOrBase):
    ID_Jobs: Optional[str] = None
    ID_Order: Optional[str] = None
    job_podio_id: Optional[str] = None


class ChangeOrUpdate(ChangeOrBase):
    ID_Jobs: Optional[str] = None
    ID_Order: Optional[str] = None
