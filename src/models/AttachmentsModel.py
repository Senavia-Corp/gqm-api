from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from .JobModel import Job
from .SubcontractorModel import Subcontractor
from .TechnicianModel import Technician
from .SupplierModel import Supplier
from .FinancialDocModel import FinancialDocument
from .GQMInventoryModel import Inventory
from .CertificateModel import Certificate
from .BldgDeptModel import BuildingDept
from .ChatModel import ChatMessage

# ==================================== Modelos para PostgreSQL ====================================#


class AttachmentsBase(SQLModel):
    Document_name: Optional[str] = Field(default=None)
    Attachment_descr: Optional[str] = Field(default=None)
    Link: Optional[str] = Field(default=None)
    Document_type: Optional[str] = Field(default=None)
    podio_file_id: Optional[str] = Field(default=None, index=True)
    # "members" | "technicians" | None
    access_level: Optional[str] = Field(default=None, index=True)
    # REG-058: identidad real en Cloudinary persistida al subir. Antes el
    # delete re-derivaba el public_id quitando la extensión de la URL — para
    # resource_type=raw (PDF/Office) el id SÍ lleva extensión y el borrado
    # fallaba en silencio para siempre.
    cloudinary_public_id: Optional[str] = Field(default=None)
    cloudinary_resource_type: Optional[str] = Field(default=None)


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
    ID_Supplier: Optional[str] = Field(
        default=None, foreign_key="supplier.ID_Supplier")
    supplier: Optional[Supplier] = Relationship(
        back_populates="attachments")
    ID_FinancialDoc: Optional[str] = Field(
        default=None, foreign_key="financial_document.ID_FinancialDoc")
    financial_document: Optional[FinancialDocument] = Relationship(
        back_populates="attachments")
    ID_Inventory: Optional[str] = Field(
        default=None, foreign_key="inventory.ID_Inventory")
    inventory: Optional[Inventory] = Relationship(
        back_populates="attachments")
    ID_Certificate: Optional[str] = Field(
        default=None, foreign_key="certificate.ID_Certificate")
    certificate: Optional[Certificate] = Relationship(
        back_populates="attachments")
    ID_BldgDept: Optional[str] = Field(
        default=None, foreign_key="bldg_dept.ID_BldgDept")
    building_dept: Optional[BuildingDept] = Relationship(
        back_populates="attachments")
    ID_ChatMessage: Optional[str] = Field(
        default=None, foreign_key="chat_message.ID_ChatMessage")
    chat_message: Optional[ChatMessage] = Relationship(
        back_populates="attachments")


class AttachmentsCreate(AttachmentsBase):
    ID_Jobs: Optional[str] = None
    ID_Subcontractor: Optional[str] = None
    ID_Technician: Optional[str] = None
    ID_Supplier: Optional[str] = None
    ID_FinancialDoc: Optional[str] = None
    ID_Inventory: Optional[str] = None
    ID_Certificate: Optional[str] = None
    ID_BldgDept: Optional[str] = None
    ID_ChatMessage: Optional[str] = None


class AttachmentsUpdate(AttachmentsBase):
    ID_Jobs: Optional[str] = None
    ID_Subcontractor: Optional[str] = None
    ID_Technician: Optional[str] = None
    ID_Supplier: Optional[str] = None
    ID_FinancialDoc: Optional[str] = None
    ID_Inventory: Optional[str] = None
    ID_Certificate: Optional[str] = None
    ID_BldgDept: Optional[str] = None
    ID_ChatMessage: Optional[str] = None


def es_fk_de_attachments(nombre: str) -> bool:
    """¿`nombre` es una columna FK real de la tabla `attachments`?

    Existe por dos motivos, y los dos son de verdad:

    1. `fk_field` llega desde `payload` (dead-letter, cuerpo del webhook) y
       termina en un `getattr(Attachments, fk_field)`. Es un limite de
       confianza: se valida contra las columnas REALES, no contra una lista
       escrita a mano que se desincroniza.

    2. `ATTACHMENT_MODEL_MAP` promete `ID_Client` (CLI) e `ID_Community_Tracking`
       (PMC) y esas columnas NO EXISTEN. SQLModel con `table=True` no valida
       nada: acepta el kwarg, lo deja como atributo suelto e inserta la fila SIN
       NINGUNA FK. En produccion hay 3 filas asi (ATT61846, ATT62109, ATT62146,
       todas de carpeta CLI y con podio_file_id) y son los unicos 3 huerfanos de
       las 2.493 — o sea, no es un riesgo teorico, es dano ya hecho.
    """
    return nombre in Attachments.model_fields and nombre.startswith("ID_")
