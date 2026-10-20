"""Database engine + session factory.

A single `engine` is built lazily from settings. Tests substitute their own
engine via `init_test_engine` and reset via `dispose_engine` so each test
sees a clean schema.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Optional

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from .base import Base

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker[Session]] = None


def init_engine(settings: Settings) -> Engine:
    """Build the global engine from settings.

    Re-calling disposes the old engine first so tests can reconfigure.
    Tests that want to keep their schema across the `create_app` call
    should use `_engine_already_bound()` to gate re-initialisation.
    """
    global _engine, _SessionLocal
    dispose_engine()
    _engine = _make_engine(settings)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def _engine_already_bound() -> bool:
    """True iff a SessionLocal + Engine have been initialised.

    `create_app` calls this to skip a re-init that would dispose the
    test-built engine.
    """
    return _SessionLocal is not None and _engine is not None


def _make_engine(settings: Settings) -> Engine:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    url = settings.database_url
    kwargs: dict[str, object] = {"future": True}
    if url.startswith("sqlite"):
        # SQLite needs special handling:
        #  - in-memory (`:memory:`) databases are per-connection, so use
        #    StaticPool to share a single connection across the suite.
        #  - allow cross-thread access (FastAPI TestClient + pytest).
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url or "mode=memory" in url:
            kwargs["poolclass"] = StaticPool
    return create_engine(url, **kwargs)


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("engine not initialised; call init_engine(settings) first")
    return _engine


def dispose_engine() -> None:
    """Tear down the engine. Used by tests between cases."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def create_all() -> None:
    """Create every table declared on `Base`. Used by tests; production uses
    Alembic migrations."""
    Base.metadata.create_all(get_engine())


def drop_all() -> None:
    """Drop every table. Tests only."""
    Base.metadata.drop_all(get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope around a series of operations. Commits on success,
    rolls back on exception, always closes."""
    if _SessionLocal is None:
        raise RuntimeError("engine not initialised; call init_engine(settings) first")
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yield a session, commit on success, close on exit."""
    if _SessionLocal is None:
        raise RuntimeError("engine not initialised; call init_engine(settings) first")
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()