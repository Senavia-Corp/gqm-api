
from sqlmodel import SQLModel, Field
from datetime import datetime
from sqlalchemy import Column, TIMESTAMP, func
from typing import Optional


class JobMultiplierRLink(SQLModel, table=True):
    __tablename__ = "job_multiplier_range"

    job_id: str = Field(
        foreign_key="jobs.ID_Jobs",
        primary_key=True
    )

    multiplier_id: str = Field(
        foreign_key="multiplier_range.ID_MultiplierR",
        primary_key=True
    )

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
