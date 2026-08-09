from sqlmodel import SQLModel, Field
from datetime import datetime
from sqlalchemy import Column, TIMESTAMP, func
from typing import Optional


class JobSubcontractorLink(SQLModel, table=True):
    __tablename__ = "job_subcontractor"

    job_id: str = Field(
        foreign_key="jobs.ID_Jobs",
        primary_key=True
    )

    subcontr_id: str = Field(
        foreign_key="subcontractor.ID_Subcontractor",
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
