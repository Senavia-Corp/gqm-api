# ==================================== Modelos para PostgreSQL ====================================#

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from enum import Enum
from .RoleModel import Role
from .MemberModel import Member
from .TechnicianModel import Technician
from .link_models.PermissionLinks import PermissionRoleLink, PermissionMemberLink, PermissionTechLink


class ActionType(str, Enum):
    View = "View"
    Create = "Create"
    Edit = "Edit"
    Delete = "Delete"


class ServiceType(str, Enum):
    Job = "Job"
    Subcontractor = "Subcontractor"
    GQM_Member = "GQM_Member"
    Technician = "Technician"
    Client = "Client"
    Dashboard = "Dashboard"


class PermissionBase(SQLModel):
    Name: Optional[str] = Field(default=None)
    Description: Optional[str] = Field(default=None)
    Active: Optional[bool] = Field(default=None)
    Action: ActionType
    Service_Associated: ServiceType


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


class PermissionUpdate(PermissionBase):
    Action: Optional[str] = None
    Service_Associated: Optional[str] = None
