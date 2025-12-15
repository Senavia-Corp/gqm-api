from sqlmodel import SQLModel, Field


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
