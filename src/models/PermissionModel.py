# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from typing import Optional, List, Dict, Any
from .RoleModel import Role
from .MemberModel import Member
from .TechnicianModel import Technician
from .link_models.PermissionLinks import PermissionRoleLink, PermissionMemberLink, PermissionTechLink


class PermissionBase(SQLModel):
    Name: Optional[str] = Field(default=None)
    Description: Optional[str] = Field(default=None)
    Active: Optional[bool] = Field(default=True)
    
    # Campo JSONB que almacenará la política tipo IAM
    # Ejemplo: {"Statement": [{"Effect": "Allow", "Action": ["job:view"], "Resource": ["*"]}]}
    Document: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB))


class Permission(PermissionBase, table=True):
    __tablename__ = "permission"

    ID_Permission: Optional[str] = Field(default=None, primary_key=True)

    # Relaciones de muchos a muchos
    roles: List[Role] = Relationship(
        back_populates="permissions",
        link_model=PermissionRoleLink
    )
    members: List[Member] = Relationship(
        back_populates="permissions",
        link_model=PermissionMemberLink
    )
    technicians: List[Technician] = Relationship(
        back_populates="permissions",
        link_model=PermissionTechLink
    )


class PermissionCreate(PermissionBase):
    pass


class PermissionUpdate(SQLModel):
    Name: Optional[str] = None
    Description: Optional[str] = None
    Active: Optional[bool] = None
    Document: Optional[Dict[str, Any]] = None
