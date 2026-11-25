"""Application settings, read from environment variables or a ``.env`` file (prefix ``SMARTAGRI_``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET = "local-development-only-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SMARTAGRI_", env_file=".env", extra="ignore")

    data_dir: Path = Field(Path("data/local"), description="Database and local working files")
    results_dir: Path | None = Field(None, description="Experiment and job results (e.g. on an external drive)")
    database_url: str | None = Field(None, description="SQLAlchemy URL; defaults to SQLite in data_dir")

    local_mode: bool = Field(True, description="Single-user mode on your own laptop: no login prompt")
    secret_key: str = DEFAULT_SECRET
    access_token_minutes: int = 12 * 60

    job_workers: int = Field(2, ge=1, le=32, description="Parallel worker processes for jobs")
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'smartagri.db').resolve().as_posix()}"

    @property
    def resolved_results_dir(self) -> Path:
        return (self.results_dir or self.data_dir / "results").resolve()

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.resolved_results_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
