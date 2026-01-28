from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from .JobModel import Job
from .SubcontractorModel import Subcontractor
from .TechnicianModel import Technician

# ==================================== Modelos para PostgreSQL ====================================#


class AttachmentsBase(SQLModel):
    Document_name: Optional[str] = Field(default=None)
    Attachment_descr: Optional[str] = Field(default=None)
    Link: Optional[str] = Field(default=None)
    Document_type: Optional[str] = Field(default=None)


class Attachments(AttachmentsBase, table=True):
    __tablename__ = "attachments"

    ID_Attachment: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas M:1
    ID_Jobs: Optional[str] = Field(
        default=None, foreign_key="jobs.ID_Jobs")
    job: Optional[Job] = Relationship(back_populates="attachments")
    ID_Subcontractor: Optional[str] = Field(
        default=None, foreign_key="subcontractor.ID_Subcontractor")
    subcontractor: Optional[Subcontractor] = Relationship(
        back_populates="attachments")
    ID_Technician: Optional[str] = Field(
        default=None, foreign_key="technician.ID_Technician")
    technician: Optional[Technician] = Relationship(
        back_populates="attachments")


class AttachmentsCreate(AttachmentsBase):
    ID_Jobs: Optional[str] = None
    ID_Subcontractor: Optional[str] = None
    ID_Technician: Optional[str] = None


class AttachmentsUpdate(AttachmentsBase):
    ID_Jobs: Optional[str] = None
    ID_Subcontractor: Optional[str] = None
    ID_Technician: Optional[str] = None
