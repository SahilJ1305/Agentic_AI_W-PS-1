import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context

# --- 1. SETUP PYTHON PATH ---
# Add the project root to path so we can import 'models' and 'database'
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# --- 2. IMPORTS ---
# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Import your Base and Models
from database.postgresConn import Base
from models import all_model  # Importing this registers the tables

# CRITICAL: Import GeoAlchemy2 so Alembic understands the "Geography" type
import geoalchemy2 

# --- 3. CONFIGURATION ---
config = context.config

# Overwrite the alembic.ini url with the real one from .env
section = config.config_ini_section
config.set_section_option(section, "sqlalchemy.url", os.environ.get("DATABASE_URL"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# --- 4. SUPABASE/POSTGIS SAFETY FILTER ---
def include_object(object, name, type_, reflected, compare_to):
    """
    Tells Alembic to IGNORE PostGIS system tables.
    If we don't do this, Alembic might try to delete 'spatial_ref_sys'.
    """
    if type_ == "table" and name == "spatial_ref_sys":
        return False
    return True

# --- 5. MIGRATION RUNNERS ---

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object, # <--- Apply the filter here
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, 
            target_metadata=target_metadata,
            include_object=include_object # <--- Apply the filter here
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()