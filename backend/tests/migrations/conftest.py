"""Shared fixtures for the Alembic migration tests.

Migrations run against a file-backed SQLite database: `:memory:` is
per-connection, and Alembic needs the schema visible to the connection it
opens as well as to the one the assertions use.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from alembic.config import Config as AlembicConfig

BACKEND_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def sqlite_url() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    url = f"sqlite:///{path}"
    yield url
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def alembic_config(sqlite_url: str, monkeypatch: pytest.MonkeyPatch) -> AlembicConfig:
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("APP_ENV", "test")

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", sqlite_url)
    return cfg