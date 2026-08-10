import sys
from pathlib import Path
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

# ------------------------------------------------------------------
# Permitir imports desde la raíz del proyecto (api/)
# ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BASE_DIR))

# ------------------------------------------------------------------
# Configuración de logging de Alembic
# ------------------------------------------------------------------
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ------------------------------------------------------------------
# IMPORTANTE:
# Importar el engine y forzar carga de modelos
# ------------------------------------------------------------------
from src.database.db_sqlmodel import engine  # noqa
import src.database.db_sqlmodel  # noqa

from sqlmodel import SQLModel  # noqa

target_metadata = SQLModel.metadata

# ------------------------------------------------------------------
# Migraciones OFFLINE (raro, pero Alembic lo pide)
# ------------------------------------------------------------------


def run_migrations_offline():
    url = engine.url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ------------------------------------------------------------------
# Migraciones ONLINE (las que usarás siempre)
# ------------------------------------------------------------------
def run_migrations_online():
    connectable = engine

    # 👇 DEBUG: ver a qué base de datos apunta Alembic
    print(f"[Alembic] Running migrations on: {engine.url}")

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # Una transacción POR revisión. Sin esto, un `upgrade head` con
            # varias revisiones corre en una sola transacción que el
            # autocommit_block de los índices CONCURRENTLY commitea a mitad:
            # si falla una revisión posterior, la base queda parcialmente
            # migrada y sin rollback. Con esto, el fallo solo revierte SU
            # revisión y alembic_version marca exactamente dónde se quedó.
            transaction_per_migration=True,
        )

        with context.begin_transaction():
            context.run_migrations()


# ------------------------------------------------------------------
# Dispatcher
# ------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
