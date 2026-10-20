"""Auth service — orchestrates users, passwords, tokens, and the blacklist.

Per the issue #2 acceptance criteria, the service layer is the single place
that knows how to:
  - create a user with a hashed password
  - verify credentials (returning the same error for unknown-user vs wrong-password)
  - mint a JWT
  - blacklist a bearer on logout
  - look up the current user from a bearer
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings
from ..db.models import AuthTokenBlacklist, User
from . import security
from .security import (
    DuplicateUserError,
    InvalidCredentialsError,
    InvalidTokenError,
    TokenClaims,
)


@dataclass(frozen=True)
class IssuedToken:
    user_id: uuid.UUID
    token: str
    expires_at: datetime


class AuthService:
    """Stateless service: pass a Session, get back dataclasses.

    Tests instantiate with a test Session; the FastAPI dependency wires
    `get_db` in `app/auth/deps.py`.
    """

    def __init__(self, session: Session, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    # --- signup -----------------------------------------------------------

    def signup(self, username: str, password: str) -> IssuedToken:
        cleaned_username = security.validate_username(username)
        pw_hash = security.hash_password(password)

        user = User(
            id=uuid.uuid4(),
            username=cleaned_username,
            password_hash=pw_hash,
        )
        self._session.add(user)
        try:
            self._session.flush()
        except IntegrityError as exc:
            # Username uniqueness violation.
            self._session.rollback()
            raise DuplicateUserError(cleaned_username) from exc

        return self._mint(user)

    # --- login ------------------------------------------------------------

    def login(self, username: str, password: str) -> IssuedToken:
        cleaned_username = security.validate_username(username)
        user = self._session.execute(
            select(User).where(User.username == cleaned_username)
        ).scalar_one_or_none()

        # Single error path: do not leak whether the username exists.
        # The cost of bcrypt is paid even for unknown users so timing does
        # not reveal account existence.
        if user is None:
            # Burn a verify cycle against a known-bad hash so the timing is
            # similar to a real wrong-password attempt.
            security.verify_password(password, _dummy_hash())
            raise InvalidCredentialsError("invalid credentials")

        if not security.verify_password(password, user.password_hash):
            raise InvalidCredentialsError("invalid credentials")

        return self._mint(user)

    # --- logout -----------------------------------------------------------

    def logout(self, token: str) -> None:
        """Insert a blacklist row for `token`. Idempotent — a second logout
        with the same bearer is a no-op."""
        claims = self._decode_or_raise(token)
        token_hash = security.sha256_hex(token)

        existing = self._session.get(AuthTokenBlacklist, token_hash)
        if existing is not None:
            return  # already blacklisted

        self._session.add(
            AuthTokenBlacklist(
                token_hash=token_hash,
                user_id=claims.user_id,
                expires_at=claims.exp,
            )
        )
        self._session.flush()

    # --- current user -----------------------------------------------------

    def get_current_user(self, token: str) -> User:
        """Resolve a bearer to the corresponding User. Raises:
          - `InvalidTokenError` on bad signature / expired / malformed claims
          - `InvalidCredentialsError` on blacklist hit (the bearer is dead)
          - `InvalidCredentialsError` on unknown `user_id` in the token
        """
        claims = self._decode_or_raise(token)

        if self._is_blacklisted(token):
            raise InvalidCredentialsError("token revoked")

        user = self._session.get(User, claims.user_id)
        if user is None:
            raise InvalidCredentialsError("user no longer exists")
        return user

    # --- internals --------------------------------------------------------

    def _mint(self, user: User) -> IssuedToken:
        token, claims = security.create_token(
            user.id,
            secret=self._settings.jwt_secret,
            algorithm=self._settings.jwt_algorithm,
            ttl_seconds=self._settings.jwt_ttl_seconds,
        )
        return IssuedToken(user_id=user.id, token=token, expires_at=claims.exp)

    def _decode_or_raise(self, token: str) -> TokenClaims:
        try:
            return security.decode_token(
                token,
                secret=self._settings.jwt_secret,
                algorithm=self._settings.jwt_algorithm,
            )
        except InvalidTokenError:
            # Surface as a generic credentials error to the API layer — no
            # information leakage about which check failed.
            raise

    def _is_blacklisted(self, token: str) -> bool:
        return self._session.get(AuthTokenBlacklist, security.sha256_hex(token)) is not None


def _dummy_hash() -> str:
    """Pre-computed bcrypt hash for the timing-equalisation path on unknown
    usernames. Generated with cost 12 so its verification cost matches a
    real hash check."""
    return "$2b$12$CwTycUXWue0Thq9StjUM0uJ8.0T4Rbq0m1A3NiGFDwEZxRxQXC3Ka"