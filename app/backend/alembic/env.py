from __future__ import annotations

from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import Table, engine_from_config, event, pool, text
from sqlalchemy.dialects.postgresql import ENUM

from app.db import Base
from app import models  # noqa: F401


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def reuse_existing_enums(table, connection, **kwargs) -> None:
    # Older migrations explicitly create enums before referencing them in tables.
    # SQLAlchemy must not issue CREATE TYPE a second time for those references.
    for column in table.columns:
        enum = column.type
        if isinstance(enum, ENUM) and connection.dialect.has_type(connection, enum.name, schema=enum.schema):
            enum.create_type = False


def get_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        config.get_main_option("sqlalchemy.url"),
    )


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        postgres = connection.dialect.name == "postgresql"
        if postgres:
            event.listen(Table, "before_create", reuse_existing_enums, insert=True)
        try:
            with context.begin_transaction():
                if postgres:
                    # Shipped revision IDs exceed Alembic 1.13's VARCHAR(32) default.
                    # Preserve existing values and applied migration files.
                    connection.execute(text(
                        "CREATE TABLE IF NOT EXISTS alembic_version "
                        "(version_num TEXT NOT NULL PRIMARY KEY)"
                    ))
                    connection.execute(text(
                        "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE TEXT"
                    ))
                context.run_migrations()
        finally:
            if postgres:
                event.remove(Table, "before_create", reuse_existing_enums)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

