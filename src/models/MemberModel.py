
# ==================================== Modelos para PostgreSQL ====================================#

from pydantic import field_validator

from src.utils.validacion_correo import validar_formato_correo
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .link_models.JobMember import JobMemberLink
from .link_models.ClientLinks import ClientMemberLink
from .RoleModel import Role
from .link_models.PermissionLinks import PermissionMemberLink


class MemberBase(SQLModel):
    Member_Name: Optional[str] = Field(default=None)
    Company_Role: Optional[str] = Field(default=None)
    Email_Address: str
    Phone_Number: Optional[str] = Field(default=None)
    Address: Optional[str] = Field(default=None)
    Password: str

    # Referencias a Podio
    podio_profile_id: Optional[str] = Field(
        default=None, index=True)
    podio_item_id: Optional[str] = Field(
        default=None, index=True)


    # El formato del correo, que es el nombre de usuario de acceso.
    # Va en la Base para que lo hereden los esquemas Create/Update, que
    # es por donde entran las escrituras HTTP. El modelo de tabla
    # (`table=True`) NO ejecuta validadores, asi que los datos que ya
    # estan en la BD se siguen leyendo sin problema.
    _validar_correo = field_validator('Email_Address')(validar_formato_correo)

class Member(MemberBase, table=True):
    __tablename__ = "member"

    ID_Member: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas M:1
    ID_Role: Optional[str] = Field(
        default=None, foreign_key="role.ID_Role")
    role: Optional[Role] = Relationship(back_populates="members")

    # Relaciones foráneas 1:M
    tlactivity: List["TLActivity"] = Relationship(  # type: ignore
        back_populates="member",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})
    purchases: List["Purchase"] = Relationship(  # type: ignore
        back_populates="member")
    tasks: List["Tasks"] = Relationship(  # type: ignore
        back_populates="member")
    chat_messages: List["ChatMessage"] = Relationship(  # type: ignore
        back_populates="member")
    commissions: List["Commission"] = Relationship(  # type: ignore
        back_populates="member",
        sa_relationship_kwargs={"cascade": "all, delete, delete-orphan"})

    # Relación de muchos a muchos
    jobs: List["Job"] = Relationship(  # type: ignore
        back_populates="members",
        link_model=JobMemberLink
    )
    clients: List["Client"] = Relationship(  # type: ignore
        back_populates="members",
        link_model=ClientMemberLink
    )
    permissions: List["Permission"] = Relationship(  # type: ignore
        back_populates="members",
        link_model=PermissionMemberLink
    )


class MemberCreate(MemberBase):
    ID_Role: Optional[str] = None


class MemberUpdate(MemberBase):
    ID_Role: Optional[str] = None
    Email_Address: Optional[str] = Field(default=None)
    Password: Optional[str] = Field(default=None)
