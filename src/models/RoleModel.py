
# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from .link_models.PermissionLinks import PermissionRoleLink


class RoleBase(SQLModel):
    Name: Optional[str] = Field(default=None)
    Description: Optional[str] = Field(default=None)
    Active: Optional[bool] = Field(default=None)


class Role(RoleBase, table=True):
    __tablename__ = "role"

    ID_Role: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones foráneas 1:M
    members: List["Member"] = Relationship(  # type: ignore
        back_populates="role")
    subcontractors: List["Subcontractor"] = Relationship(  # type: ignore
        back_populates="role")

    # Relaciones de muchos a muchos
    permissions: List["Permission"] = Relationship(  # type: ignore
        back_populates="roles",
        link_model=PermissionRoleLink
    )


class RoleCreate(RoleBase):
    pass


class RoleUpdate(RoleBase):
    pass
