
# ==================================== Modelos para PostgreSQL ====================================#

from datetime import date
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .SubcontractorModel import Subcontractor


class CertificateBase(SQLModel):
    Name: Optional[str] = Field(default=None)
    Status: Optional[str] = Field(default=None)
    Expiration_date: Optional[date] = Field(default=None)
    Notes: Optional[str] = Field(default=None)
    Current_doc_id: Optional[str] = Field(default=None)


class Certificate(CertificateBase, table=True):
    __tablename__ = "certificate"

    ID_Certificate: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas M:1
    ID_Subcontractor: Optional[str] = Field(
        default=None, foreign_key="subcontractor.ID_Subcontractor")
    subcontractor: Optional[Subcontractor] = Relationship(
        back_populates="certificates")

    # Relaciones foráneas 1:M
    attachments: List["Attachments"] = Relationship(  # type: ignore
        back_populates="certificate",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})


class CertificateCreate(CertificateBase):
    ID_Subcontractor: Optional[str] = None


class CertificateUpdate(CertificateBase):
    ID_Subcontractor: Optional[str] = None
