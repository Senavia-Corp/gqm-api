
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .JobModel import Job
from .OrderModel import Order


class EstimateBase(SQLModel):
    Title: Optional[str] = Field(default=None)
    Cost_code: Optional[str] = Field(default=None)
    Category: Optional[str] = Field(default=None)
    Parent_group: Optional[str] = Field(default=None)
    Description: Optional[str] = Field(default=None)
    Quatity: Optional[float] = Field(default=None)
    Unit: Optional[str] = Field(default=None)
    Unit_cost: Optional[float] = Field(default=None)
    Cost_type: Optional[str] = Field(default=None)
    Builder_cost: Optional[float] = Field(default=None)
    Client_price: Optional[float] = Field(default=None)
    Markup: Optional[float] = Field(default=None)
    Margin: Optional[float] = Field(default=None)
    Percent_invoiced: Optional[float] = Field(default=None)
    Status: Optional[str] = Field(default=None)


class EstimateCost(EstimateBase, table=True):
    __tablename__ = "estimate_cost"

    ID_EstimateCost: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas M:1
    ID_Jobs: Optional[str] = Field(
        default=None, foreign_key="jobs.ID_Jobs")
    job: Optional[Job] = Relationship(back_populates="estimate_costs")
    ID_Order: Optional[str] = Field(
        default=None, foreign_key="order.ID_Order")
    order: Optional[Order] = Relationship(back_populates="estimate_costs")


class EstimateCreate(EstimateBase):
    ID_Jobs: Optional[str] = None
    ID_Order: Optional[str] = None


class EstimateUpdate(EstimateBase):
    ID_Jobs: Optional[str] = None
    ID_Order: Optional[str] = None
