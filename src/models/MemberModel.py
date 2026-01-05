
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
# agregar modelo de Rol cuando se cree
from .link_models.JobMember import JobMemberLink
from .link_models.ClientMember import ClientMemberLink


class MemberBase(SQLModel):
    Member_Name: Optional[str] = Field(default=None)
    Email_Address: str
    Phone_Number: Optional[str] = Field(default=None)
    Address: Optional[str] = Field(default=None)
    Password: str


class Member(MemberBase, table=True):
    __tablename__ = "member"

    ID_Member: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas
    # ID_Rol: Optional[str] = Field(default=None, foreign_key="rol.ID_Rol")
    # rol: Optional["Rol"] = Relationship()

    # Relación de muchos a muchos
    jobs: List["Job"] = Relationship(  # type: ignore
        back_populates="members",
        link_model=JobMemberLink
    )
    clients: List["Client"] = Relationship(  # type: ignore
        back_populates="members",
        link_model=ClientMemberLink
    )


class MemberCreate(MemberBase):
    pass
    # ID_Rol: Optional[str] = None


class MemberUpdate(MemberBase):
    # ID_Rol: Optional[str] = None
    Email_Address: Optional[str] = Field(default=None)
    Password: Optional[str] = Field(default=None)

# Info relacionadas con Rol estan comentadas hasta crear tabla
