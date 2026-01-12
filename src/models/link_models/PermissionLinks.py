from sqlmodel import SQLModel, Field


# Tabla intermedia con Role
class PermissionRoleLink(SQLModel, table=True):
    __tablename__ = "permission_role"

    permission_id: str = Field(
        foreign_key="permission.ID_Permission",
        primary_key=True
    )

    role_id: str = Field(
        foreign_key="role.ID_Role",
        primary_key=True
    )


# Tabla intermedia con GQM Member
class PermissionMemberLink(SQLModel, table=True):
    __tablename__ = "permission_member"

    permission_id: str = Field(
        foreign_key="permission.ID_Permission",
        primary_key=True
    )

    member_id: str = Field(
        foreign_key="member.ID_Member",
        primary_key=True
    )


# Tabla intermedia con Technician
class PermissionTechLink(SQLModel, table=True):
    __tablename__ = "permission_tech"

    permission_id: str = Field(
        foreign_key="permission.ID_Permission",
        primary_key=True
    )

    tech_id: str = Field(
        foreign_key="technician.ID_Technician",
        primary_key=True
    )
