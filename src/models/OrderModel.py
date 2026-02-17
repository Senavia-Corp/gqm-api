
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .SubcontractorModel import Subcontractor


class OrderBase(SQLModel):
    Title: Optional[str] = Field(default=None)
    Formula: Optional[float] = Field(default=None)
    Adj_formula: Optional[float] = Field(default=None)
    Notes: Optional[str] = Field(default=None)  # De PAR
    Ptl_hd_materials: Optional[float] = Field(default=None)  # De PTL
    # Para poder conectar con Podio si se hacen modificaciones
    job_podio_id: Optional[str] = Field(default=None)
    # Para guardar el external id de TECH Formula de Job (Podio)
    tech_field: Optional[str] = Field(default=None)
    # Para guardar el external id de HD_Materials de Job (Podio)
    hd_materials_field: Optional[str] = Field(default=None)
    # Para guardar el external id de Description de Job (Podio)
    notes_field: Optional[str] = Field(default=None)


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
    change_orders: List["ChangeOrder"] = Relationship(  # type: ignore
        back_populates="order")


class OrderCreate(OrderBase):
    ID_Subcontractor: Optional[str] = None


class OrderUpdate(OrderBase):
    ID_Subcontractor: Optional[str] = None
