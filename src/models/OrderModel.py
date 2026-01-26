
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .SubcontractorModel import Subcontractor


class OrderBase(SQLModel):
    Title: Optional[str] = Field(default=None)
    Formula: Optional[float] = Field(default=None)
    Adj_formula: Optional[float] = Field(default=None)

    job_podio_id: Optional[str] = Field(default=None)
    # Para guardar el external id del campo TECH Formula de Podio
    tech_field: Optional[str] = Field(default=None)


class Order(OrderBase, table=True):
    __tablename__ = "order"

    ID_Order: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas M:1
    ID_Subcontractor: Optional[str] = Field(
        default=None, foreign_key="subcontractor.ID_Subcontractor")
    subcontractor: Optional["Subcontractor"] = Relationship(
        back_populates="orders")

    # Relaciones foráneas 1:M
    estimate_costs: List["EstimateCost"] = Relationship(  # type: ignore
        back_populates="order")
    financial_docs: List["FinancialDocument"] = Relationship(  # type: ignore
        back_populates="order")


class OrderCreate(OrderBase):
    ID_Subcontractor: Optional[str] = None


class OrderUpdate(OrderBase):
    ID_Subcontractor: Optional[str] = None
