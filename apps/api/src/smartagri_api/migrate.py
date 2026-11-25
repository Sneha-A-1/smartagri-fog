"""Run Alembic migrations programmatically, so starting the API always brings the database up to date."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def run_migrations(url: str) -> None:
    command.upgrade(alembic_config(url), "head")
