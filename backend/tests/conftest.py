"""Shared pytest fixtures.

Tests use an in-memory SQLite database so the suite runs without a
PostgreSQL instance. The schema is built from `Base.metadata` at session
start and dropped at session end.
"""

from __future__ import annotations

import os

# Set sane test defaults BEFORE importing the app so `get_settings()` does
# not blow up. Individual tests may override via fixtures.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-real-use")
os.environ.setdefault("APP_ENV", "test")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db.session import dispose_engine, get_engine, init_engine, session_scope  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        database_url="sqlite:///:memory:",
        jwt_secret="test-secret-not-for-real-use",
        jwt_algorithm="HS256",
        jwt_ttl_seconds=3600,
        app_env="test",
    )


@pytest.fixture(autouse=True)
def _engine(settings: Settings) -> Iterator[None]:
    init_engine(settings)
    # Recreate schema for each test so tests are isolated.
    from app.db.base import Base

    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    dispose_engine()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """A FastAPI TestClient with a clean DB for each test."""
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db_session(settings: Settings) -> Iterator:
    """A Session for direct DB inspection (e.g. verifying blacklist rows).

    The `_engine` autouse fixture has already initialised the engine by the
    time this runs, so we reuse it without re-binding.
    """
    with session_scope() as session:
        yield session