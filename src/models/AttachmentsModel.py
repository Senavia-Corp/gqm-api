from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .JobModel import Job

# ==================================== Modelos para PostgreSQL ====================================#


class AttachmentsBase(SQLModel):
    Document_name: Optional[str] = Field(default=None)
    Attachment_descr: Optional[str] = Field(default=None)
    Link: Optional[str] = Field(default=None)
    Document_type: Optional[str] = Field(default=None)


class Attachments(AttachmentsBase, table=True):
    __tablename__ = "attachments"

    ID_Attachment: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas 1:M
    ID_Jobs: Optional[str] = Field(
        default=None, foreign_key="jobs.ID_Jobs")
    job: Optional["Job"] = Relationship(back_populates="attachments")


class AttachmentsCreate(AttachmentsBase):
    ID_Jobs: Optional[str] = None


class AttachmentsUpdate(AttachmentsBase):
    ID_Jobs: Optional[str] = None
