
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .SubcontractorModel import Subcontractor
from datetime import datetime
from sqlalchemy import Column, TIMESTAMP, func


class OrderBase(SQLModel):
    Title: Optional[str] = Field(default=None)
    Formula: Optional[float] = Field(default=None)
    Adj_formula: Optional[float] = Field(default=None)
    Notes: Optional[str] = Field(default=None)  # De PAR
    Ptl_hd_materials: Optional[float] = Field(default=None)  # De PTL
    # Cuotas de PAR (decisión 2026-08-08): Formula = total del tech y cada
    # Payment_N es un cheque parcial sincronizado desde Podio
    # (check-amount-payment-N / tech-N-payment-N). Solo aplica a PAR.
    Payment_1: Optional[float] = Field(default=None)
    Payment_2: Optional[float] = Field(default=None)
    Payment_3: Optional[float] = Field(default=None)
    # Para guardar el external id de TECH Formula de Job (Podio)
    tech_field: Optional[str] = Field(default=None)


class Order(OrderBase, table=True):
    __tablename__ = "order"

    ID_Order: Optional[str] = Field(default=None, primary_key=True)

    # Para poder conectar con Podio si se hacen modificaciones
    job_podio_id: Optional[str] = Field(default=None)

    # Relaciones foráneas M:1
    ID_Subcontractor: Optional[str] = Field(
        default=None, foreign_key="subcontractor.ID_Subcontractor")
    subcontractor: Optional["Subcontractor"] = Relationship(
        back_populates="orders")

    # Relaciones foráneas 1:M
    estimate_costs: List["EstimateCost"] = Relationship(  # type: ignore
        back_populates="order")
    change_orders: List["ChangeOrder"] = Relationship(  # type: ignore
        back_populates="order",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})
    financial_docs: List["FinancialDocument"] = Relationship(  # type: ignore
        back_populates="order")
    opportunities: List["Opportunities"] = Relationship(  # type: ignore
        back_populates="order")

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

class OrderCreate(OrderBase):
    ID_Subcontractor: Optional[str] = None
    job_podio_id: Optional[str] = None
    estimate_cost_ids: Optional[List[str]] = None
    ID_FinancialDoc: Optional[str] = None


class OrderUpdate(OrderBase):
    ID_Subcontractor: Optional[str] = None
