
from sqlmodel import SQLModel, Field


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
