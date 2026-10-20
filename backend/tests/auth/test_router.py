"""HTTP-level tests for the /auth/* endpoints.

Exercises the full request → router → service → DB path through FastAPI's
TestClient so the wiring is verified, not just the units.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db.models import AuthTokenBlacklist, User


def _signup(client: TestClient, username: str = "alice", password: str = "hunter2") -> dict:
    r = client.post("/auth/signup", json={"username": username, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestSignup:
    def test_signup_returns_201_with_token_and_user_id(self, client: TestClient) -> None:
        body = _signup(client)
        assert "token" in body and isinstance(body["token"], str)
        assert "user_id" in body and uuid.UUID(body["user_id"])  # parses as UUID

    def test_signup_duplicate_returns_409(self, client: TestClient) -> None:
        _signup(client, username="alice")
        r = client.post("/auth/signup", json={"username": "alice", "password": "x"})
        assert r.status_code == 409

    def test_signup_short_password_returns_422(self, client: TestClient) -> None:
        r = client.post("/auth/signup", json={"username": "alice", "password": ""})
        assert r.status_code == 422

    def test_signup_long_password_returns_422(self, client: TestClient) -> None:
        # 73 bytes is past bcrypt's limit; the schema also caps it at 72.
        r = client.post("/auth/signup", json={"username": "alice", "password": "x" * 73})
        assert r.status_code == 422

    def test_signup_empty_username_returns_422(self, client: TestClient) -> None:
        r = client.post("/auth/signup", json={"username": "", "password": "hunter2"})
        assert r.status_code == 422

    def test_signup_username_whitespace_only_returns_422(
        self, client: TestClient
    ) -> None:
        r = client.post("/auth/signup", json={"username": "   ", "password": "hunter2"})
        assert r.status_code == 422

    def test_password_is_hashed_not_stored_in_plain(
        self, client: TestClient, db_session
    ) -> None:
        body = _signup(client, password="hunter2")
        row = db_session.execute(
            select(User).where(User.id == uuid.UUID(body["user_id"]))
        ).scalar_one()
        assert row.password_hash != "hunter2"
        assert row.password_hash.startswith("$2")


class TestLogin:
    def test_login_returns_200_with_token_and_user_id(self, client: TestClient) -> None:
        _signup(client, username="alice", password="hunter2")
        r = client.post("/auth/login", json={"username": "alice", "password": "hunter2"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "token" in body
        assert uuid.UUID(body["user_id"])

    def test_login_wrong_password_returns_401(self, client: TestClient) -> None:
        _signup(client, username="alice", password="hunter2")
        r = client.post("/auth/login", json={"username": "alice", "password": "WRONG"})
        assert r.status_code == 401

    def test_login_unknown_user_returns_401(self, client: TestClient) -> None:
        r = client.post("/auth/login", json={"username": "ghost", "password": "hunter2"})
        assert r.status_code == 401

    def test_login_wrong_password_and_unknown_user_share_message(
        self, client: TestClient
    ) -> None:
        # Same message string — no information leakage about whether the
        # username exists.
        _signup(client, username="alice", password="hunter2")
        a = client.post("/auth/login", json={"username": "alice", "password": "WRONG"})
        b = client.post("/auth/login", json={"username": "ghost", "password": "WRONG"})
        assert a.status_code == b.status_code == 401
        assert a.json() == b.json()

    def test_login_empty_password_returns_422(self, client: TestClient) -> None:
        _signup(client)
        r = client.post("/auth/login", json={"username": "alice", "password": ""})
        assert r.status_code == 422


class TestMe:
    def test_me_returns_200_with_user_fields(self, client: TestClient) -> None:
        body = _signup(client, username="alice")
        r = client.get("/auth/me", headers=_bearer(body["token"]))
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "alice"
        assert data["user_id"] == body["user_id"]
        # `created_at` is ISO-8601-ish.
        datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))

    def test_me_without_bearer_returns_401(self, client: TestClient) -> None:
        r = client.get("/auth/me")
        assert r.status_code == 401

    def test_me_with_garbage_bearer_returns_401(self, client: TestClient) -> None:
        r = client.get("/auth/me", headers=_bearer("not-a-real-token"))
        assert r.status_code == 401

    def test_me_with_wrong_scheme_returns_401(self, client: TestClient) -> None:
        r = client.get("/auth/me", headers={"Authorization": "Basic abc"})
        assert r.status_code == 401

    def test_me_with_expired_token_returns_401(
        self, client: TestClient, settings: Settings
    ) -> None:
        # Mint a token that's already expired, then try /auth/me.
        uid = uuid.uuid4()
        expired = jwt.encode(
            {
                "user_id": str(uid),
                "exp": int(datetime.now(timezone.utc).timestamp()) - 1,
                "iat": int(datetime.now(timezone.utc).timestamp()) - 10,
            },
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        r = client.get("/auth/me", headers=_bearer(expired))
        assert r.status_code == 401


class TestLogout:
    def test_logout_returns_204(self, client: TestClient) -> None:
        body = _signup(client)
        r = client.post("/auth/logout", headers=_bearer(body["token"]))
        assert r.status_code == 204
        assert r.content == b""

    def test_logout_writes_blacklist_row(
        self, client: TestClient, db_session, settings: Settings
    ) -> None:
        body = _signup(client)
        token = body["token"]
        r = client.post("/auth/logout", headers=_bearer(token))
        assert r.status_code == 204

        # Verify the row was written with the right shape.
        row = db_session.execute(
            select(AuthTokenBlacklist).where(
                AuthTokenBlacklist.token_hash == hashlib.sha256(token.encode()).hexdigest()
            )
        ).scalar_one()
        assert row.user_id == uuid.UUID(body["user_id"])
        assert row.expires_at >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)

    def test_logout_then_me_returns_401(self, client: TestClient) -> None:
        body = _signup(client)
        token = body["token"]
        assert client.post("/auth/logout", headers=_bearer(token)).status_code == 204
        assert client.get("/auth/me", headers=_bearer(token)).status_code == 401

    def test_logout_without_bearer_returns_401(self, client: TestClient) -> None:
        r = client.post("/auth/logout")
        assert r.status_code == 401

    def test_logout_is_idempotent(self, client: TestClient) -> None:
        """A second logout with the same bearer is a no-op (still 204).

        The blacklist row already exists, so `AuthService.logout` short-
        circuits without raising. The token will still 401 on any
        /sessions* call after this — verified by `test_logout_then_me_returns_401`.
        """
        body = _signup(client)
        h = _bearer(body["token"])
        assert client.post("/auth/logout", headers=h).status_code == 204
        assert client.post("/auth/logout", headers=h).status_code == 204

    def test_logout_does_not_affect_other_users(
        self, client: TestClient, db_session
    ) -> None:
        a = _signup(client, username="alice")
        b = _signup(client, username="bob")

        assert client.post("/auth/logout", headers=_bearer(a["token"])).status_code == 204

        # Bob's token still works.
        assert client.get("/auth/me", headers=_bearer(b["token"])).status_code == 200


class TestSessionEndpointsGuard:
    """The issue #2 acceptance says /sessions* must 401 without a bearer.

    P1 only ships the auth router — the session endpoints land in later
    tickets. This test stands up a probe route that depends on the same
    `get_current_user` guard so we can verify the 401-on-no-bearer behaviour
    before the real /sessions* surfaces arrive in #3.
    """

    @pytest.fixture
    def app_with_probe(self, settings: Settings):
        from fastapi import APIRouter, Depends, FastAPI

        from app.auth.deps import get_current_user
        from app.db.models import User
        from app.db.session import _engine_already_bound, init_engine

        if not _engine_already_bound():
            init_engine(settings)

        probe_app = FastAPI()

        @probe_app.get("/_probe")
        def probe_route(current: User = Depends(get_current_user)) -> dict:
            return {"user_id": str(current.id)}

        return probe_app

    def test_guarded_route_requires_bearer(self, app_with_probe) -> None:
        with TestClient(app_with_probe) as c:
            r = c.get("/_probe")
        assert r.status_code == 401

    def test_guarded_route_accepts_valid_bearer(
        self, app_with_probe, client: TestClient
    ) -> None:
        body = _signup(client)
        with TestClient(app_with_probe) as c:
            r = c.get("/_probe", headers=_bearer(body["token"]))
        assert r.status_code == 200
        assert r.json()["user_id"] == body["user_id"]