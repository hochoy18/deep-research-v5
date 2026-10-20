"""CORS configuration tests.

The browser calls the API cross-origin (the Next.js dev server is a
different origin from uvicorn), so without CORS every request dies in the
browser before it reaches a route — a failure that no backend test can see,
because the tests all use `TestClient`, which does not enforce the
same-origin policy.

The origins come from configuration, not from a literal in the source
(ADR 0002): which origins are trusted is an operator's decision.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings


def _settings(**kwargs: object) -> Settings:
    defaults = {
        "database_url": "sqlite:///:memory:",
        "jwt_secret": "test-secret-not-for-real-use",
    }
    return Settings(**{**defaults, **kwargs})  # type: ignore[arg-type]


class TestCors:
    def test_preflight_from_a_configured_origin_is_allowed(self) -> None:
        app_client = TestClient(_app(cors_origins=["http://localhost:3000"]))

        r = app_client.options(
            "/sessions",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
        assert "authorization" in r.headers["access-control-allow-headers"].lower()

    def test_an_unconfigured_origin_gets_no_allow_header(self) -> None:
        app_client = TestClient(_app(cors_origins=["http://localhost:3000"]))

        r = app_client.options(
            "/sessions",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )

        assert "access-control-allow-origin" not in r.headers

    def test_no_configured_origins_means_no_cors_middleware(self) -> None:
        """An unset CORS_ORIGINS must not turn into `*` — the API is
        bearer-authenticated, and a wildcard would let any site drive a
        logged-in browser."""
        app_client = TestClient(_app(cors_origins=[]))

        r = app_client.options(
            "/sessions",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )

        assert "access-control-allow-origin" not in r.headers


def _app(**kwargs: object):
    from app.main import create_app

    return create_app(_settings(**kwargs))  # type: ignore[arg-type]