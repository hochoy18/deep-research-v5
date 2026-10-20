"""Application configuration.

Reads from environment variables. Per ADR 0002 no URL or credential may be
hard-coded; the same `.env.example` documents every variable for operators.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Bailian's OpenAI-compatible endpoint. Not a deployment-specific value —
# it is the provider's own fixed address, overridable with
# DASHSCOPE_BASE_URL for a proxy or a regional endpoint.
DASHSCOPE_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@dataclass(frozen=True)
class LLMSettings:
    """Everything the `call_llm` seam needs to reach a model.

    Kept separate from `Settings` so a seam call never requires a database
    URL or a JWT secret — LLM configuration is readable on its own.

    `provider` is `dashscope` (Bailian, OpenAI-compatible API) or `stub`
    (deterministic offline output for dev/demo). Defaulting to `dashscope`
    means an unconfigured deployment fails closed rather than silently
    serving fake plans (ADR 0004).
    """

    provider: str = "dashscope"
    dashscope_api_key: str | None = None
    dashscope_base_url: str = DASHSCOPE_DEFAULT_BASE_URL
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    prompt_cache_ttl_seconds: int = 60
    request_timeout_seconds: float = 60.0

    @property
    def langfuse_configured(self) -> bool:
        return bool(self.langfuse_host and self.langfuse_public_key and self.langfuse_secret_key)


def get_llm_settings() -> LLMSettings:
    """Build the LLM settings from the environment. Never raises."""
    return LLMSettings(
        provider=os.getenv("LLM_PROVIDER", "dashscope"),
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"),
        dashscope_base_url=os.getenv("DASHSCOPE_BASE_URL", DASHSCOPE_DEFAULT_BASE_URL),
        langfuse_host=os.getenv("LANGFUSE_BASE_URL"),
        langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        prompt_cache_ttl_seconds=int(os.getenv("PROMPT_CACHE_TTL_SECONDS", "60")),
        request_timeout_seconds=float(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "60")),
    )


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

    # Browser origins allowed to call this API. The Next.js dev server
    # runs on its own origin, so without at least one entry every request
    # is blocked in the browser — invisible to `TestClient`, which does not
    # enforce the same-origin policy. Empty means CORS is off entirely
    # rather than `*`: the API is bearer-authenticated, and a wildcard
    # would let any site drive a logged-in browser.
    cors_origins: tuple[str, ...] = ()

    # LLM / prompt registry (Bailian primary, Langfuse as the prompt SSOT)
    llm: LLMSettings = field(default_factory=get_llm_settings)

    # Reserved for later tickets (tavily, checkpoints db, ...). Listed here
    # so operators can see the full surface in one place.
    # tavily_api_key: str | None = None
    # langgraph_checkpoints_db_url: str | None = None


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required (see .env.example)")
    return value


def get_settings() -> Settings:
    """Build the Settings dataclass from environment variables."""
    return Settings(
        database_url=_required("DATABASE_URL"),
        jwt_secret=_required("JWT_SECRET"),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        jwt_ttl_seconds=int(os.getenv("JWT_TTL_SECONDS", "86400")),
        app_env=os.getenv("APP_ENV", "production"),
        cors_origins=_cors_origins(),
        llm=get_llm_settings(),
    )


def _cors_origins() -> tuple[str, ...]:
    """`CORS_ORIGINS` as a comma-separated list; empty when unset."""
    raw = os.getenv("CORS_ORIGINS", "")
    return tuple(origin.strip() for origin in raw.split(",") if origin.strip())