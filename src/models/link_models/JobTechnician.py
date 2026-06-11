from sqlmodel import SQLModel, Field


class JobTechnicianLink(SQLModel, table=True):
    __tablename__ = "job_technician"

    job_id: str = Field(
        foreign_key="jobs.ID_Jobs",
        primary_key=True
    )

    technician_id: str = Field(
        foreign_key="technician.ID_Technician",
        primary_key=True
    )
