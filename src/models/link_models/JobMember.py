
from sqlmodel import SQLModel, Field


class JobMemberLink(SQLModel, table=True):
    __tablename__ = "job_member"

    job_id: str = Field(
        foreign_key="jobs.ID_Jobs",
        primary_key=True
    )

    member_id: str = Field(
        foreign_key="member.ID_Member",
        primary_key=True
    )
