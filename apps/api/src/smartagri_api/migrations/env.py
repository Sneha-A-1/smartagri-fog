"""Alembic environment. Uses SQLite batch mode so columns can be altered on SQLite."""

from __future__ import annotations

from alembic import context
from smartagri_api import models  # noqa: F401  (registers tables on Base.metadata)
from smartagri_api.config import get_settings
from smartagri_api.db import Base
from sqlalchemy import engine_from_config, pool

config = context.config
url = config.get_main_option("sqlalchemy.url") or get_settings().resolved_database_url
target_metadata = Base.metadata


def run_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = url
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
