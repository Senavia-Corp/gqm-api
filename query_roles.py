from sqlmodel import Session, select
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))
from src.database.db_sqlmodel import engine
from src.models.RoleModel import Role
from src.models.PermissionModel import Permission

with Session(engine) as session:
    roles = session.exec(select(Role)).all()
    for r in roles:
        print(f"Role: {r.Name} (ID: {r.ID_Role})")
        for p in r.permissions:
            print(f"  - Permission: {p.Name}")
            print(f"    Document: {p.Document}")
