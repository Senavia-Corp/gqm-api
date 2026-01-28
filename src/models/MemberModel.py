
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .link_models.JobMember import JobMemberLink
from .link_models.ClientLinks import ClientMemberLink
from .RoleModel import Role
from .link_models.PermissionLinks import PermissionMemberLink


class MemberBase(SQLModel):
    Member_Name: Optional[str] = Field(default=None)
    Email_Address: str
    Phone_Number: Optional[str] = Field(default=None)
    Address: Optional[str] = Field(default=None)
    Password: str


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
