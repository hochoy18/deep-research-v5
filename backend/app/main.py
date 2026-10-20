"""FastAPI application factory.

Wires the global engine, the auth router, and any future routers. Routers
are mounted in this file so the rest of the codebase stays decoupled.

The module deliberately does **not** instantiate `app` at import time so
that test suites can build their own app with custom settings without
triggering `get_settings()` (which requires DATABASE_URL). Production
launches via `uvicorn app.main:app` use the `app` attribute below, which
is set lazily on first access.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.sessions import router as sessions_router
from .auth import router as auth_router
from .config import Settings, get_settings
from .db.session import init_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a FastAPI app bound to `settings`. Tests pass a fixture.

    The engine is initialised here in production, but only when no engine
    is already bound. Tests pre-bind via `init_engine(settings)` so the
    schema built in the fixture is preserved across the call.
    """
    from .db.session import _engine_already_bound, init_engine

    settings = settings or get_settings()
    if not _engine_already_bound():
        init_engine(settings)

    app = FastAPI(title="Deep Research v5 — backend", version="0.1.0")

    # Added only when origins are configured: no `CORS_ORIGINS` means the
    # browser never gets an allow header, which is the safe default for a
    # bearer-authenticated API served same-origin in production.
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(auth_router)
    app.include_router(sessions_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


def __getattr__(name: str):  # PEP 562 lazy module attribute
    """Lazy `app` for `uvicorn app.main:app`.

    Only constructed when actually accessed — keeps tests from triggering
    `get_settings()` at import time. The result is cached in the module
    namespace, so a module-level `app = None` must NOT be defined here:
    a real name in the namespace would shadow `__getattr__` entirely and
    `uvicorn app.main:app` would try to serve `None`.
    """
    if name == "app":
        globals()["app"] = application = create_app()
        return application
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _configure_logging() -> None:
    """Quiet down the default loggers when running under pytest."""
    if logging.getLogger().handlers:
        return
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


_configure_logging()