"""Cuotas (cheques parciales) pagadas a un técnico por una orden.

## Por qué una tabla nueva y no algo de lo que ya hay

- **`PaymentUnit`** es el lado del **cobro** — lo que el cliente le paga a GQM
  (`Payment Received 1..3`, `Amount Left To Collect`). Va en M:N con `Job`, sin
  vínculo a orden ni a técnico. Meter aquí los cheques al técnico mezclaría
  cuentas por cobrar con cuentas por pagar.
- **`FinancialTransaction` / `FinancialDocument`** son propiedad del sync de
  QuickBooks: `qbo_id` único, su propia cola de fallos y su backfill de
  `amount_applied`. Un segundo escritor rompería sus invariantes de balance.

La identidad aquí es `(orden, cuota)` y su verdad vive en un hueco de campo de
Podio. Eso es exactamente la forma de `ChangeOrder`, no la de `PaymentUnit`.

## Por qué no bastaban `Order.Payment_1/2/3`

QID llega a **11 cuotas por técnico**. Tres columnas no caben. `Payment_1/2/3`
se conservan como proyección de solo lectura de las cuotas 1..3 mientras el
panel se adapta.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Column, ForeignKey, String, TIMESTAMP, func
from sqlmodel import Field, Relationship, SQLModel

from .OrderModel import Order


class OrderPaymentBase(SQLModel):
    Amount: Optional[float] = Field(default=None)
    # Número de cuota dentro de la sección del técnico (1..11 en QID).
    Installment: Optional[int] = Field(default=None)
    Date: Optional[date] = Field(default=None)
    # Propio del panel. NO se sincroniza: el `Check Number(s)` de Podio es uno
    # por sección, así que componerlo desde N cuotas pisaría lo escrito a mano.
    Check_number: Optional[str] = Field(default=None)


class OrderPayment(OrderPaymentBase, table=True):
    __tablename__ = "order_payment"

    ID_OrderPayment: Optional[str] = Field(default=None, primary_key=True)

    # `external_id` del hueco de Podio que ocupa esta cuota. Fuera del Base a
    # propósito: la API no reasigna huecos a mano.
    podio_field: Optional[str] = Field(default=None, index=True)

    # `ondelete="CASCADE"` no es cosmético: `Webhook_bp.py` y `Job.py` borran
    # órdenes en masa con SQL directo, y una hija sin cascada abortaría el
    # borrado entero con ForeignKeyViolation.
    ID_Order: Optional[str] = Field(
        default=None,
        sa_column=Column(String, ForeignKey("order.ID_Order", ondelete="CASCADE"),
                         index=True))
    order: Optional[Order] = Relationship(back_populates="payments")

    job_podio_id: Optional[str] = Field(default=None, index=True)

    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True), server_default=func.now(),
                         nullable=False))
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True), server_default=func.now(),
                         onupdate=func.now(), nullable=False))


class OrderPaymentCreate(OrderPaymentBase):
    ID_Order: Optional[str] = None


class OrderPaymentUpdate(OrderPaymentBase):
    pass
