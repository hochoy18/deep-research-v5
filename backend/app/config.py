"""Application configuration.

Reads from environment variables. Per ADR 0002 no URL or credential may be
hard-coded; the same `.env.example` documents every variable for operators.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Database
    database_url: str

    # Auth / JWT
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_ttl_seconds: int = 24 * 60 * 60  # 24 hours per issue #2 acceptance

    # App environment
    app_env: str = "production"

    # Reserved for future tickets (Langfuse, dashscope, tavily, ...). Listed
    # here so operators can see the full surface in one place.
    # langfuse_host: str | None = None
    # langfuse_public_key: str | None = None
    # langfuse_secret_key: str | None = None
    # dashscope_api_key: str | None = None
    # tavily_api_key: str | None = None
    # langgraph_checkpoints_db_url: str | None = None


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required (see .env.example)")
    return value


def get_settings() -> Settings:
    """Build the Settings dataclass from environment variables.

    Test code calls the variant free `_make(**overrides)` helper instead so it
    can avoid touching the real environment.
    """
    return Settings(
        database_url=_required("DATABASE_URL"),
        jwt_secret=_required("JWT_SECRET"),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        jwt_ttl_seconds=int(os.getenv("JWT_TTL_SECONDS", "86400")),
        app_env=os.getenv("APP_ENV", "production"),
    )


def _make(**overrides: object) -> Settings:
    """Test helper: build a Settings dataclass with explicit overrides."""
    defaults: dict[str, object] = {
        "database_url": "sqlite:///:memory:",
        "jwt_secret": "test-secret-do-not-use-in-prod",
        "jwt_algorithm": "HS256",
        "jwt_ttl_seconds": 86400,
        "app_env": "test",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]