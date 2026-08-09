from datetime import datetime
from typing import Optional

from sqlalchemy import Column, TIMESTAMP, func
from sqlmodel import Field, SQLModel


class QboFailedEvent(SQLModel, table=True):
    """Dead-letter de eventos del webhook QBO (REG-057/REG-118).

    Intuit recibe 200 siempre (no reintenta); si un evento falla se persiste
    aquí para reprocesarlo vía /webhook/qbo/failed_events/<id>/retry.
    """

    __tablename__ = "qbo_failed_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    realm_id: Optional[str] = Field(default=None)
    entity_name: Optional[str] = Field(default=None, index=True)
    entity_id: Optional[str] = Field(default=None, index=True)
    operation: Optional[str] = Field(default=None)
    error_message: Optional[str] = Field(default=None)
    resolved: bool = Field(default=False)

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
