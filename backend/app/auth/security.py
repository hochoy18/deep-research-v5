"""Password hashing and JWT helpers.

Per the issue #2 acceptance criteria:
  - Password storage: bcrypt, cost 12.
  - JWT: HS256, 24-hour TTL, claims contain `user_id` and `exp`.
  - The `auth_token_blacklist` row stores the SHA-256 of the bearer token.

The seam-style discipline forbids importing bcrypt / PyJWT outside this
file: the rest of the project uses `hash_password`, `verify_password`,
`create_token`, `decode_token`.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

# Per issue #2 acceptance: cost 12.
BCRYPT_ROUNDS = 12

# JWT lifetime, defaulting to 24h. Tests can pass a smaller value.
DEFAULT_JWT_TTL = 24 * 60 * 60


class AuthError(Exception):
    """Base class for auth-layer errors. Specifics extend this."""


class InvalidCredentialsError(AuthError):
    """Wrong username or password — single error regardless of which one is wrong."""


class InvalidTokenError(AuthError):
    """Token signature, claim, or expiry is invalid."""


class DuplicateUserError(AuthError):
    """Username is already taken; surfaced as HTTP 409."""


class WeakPasswordError(AuthError):
    """Password failed field-level bounds (≤72 bytes for bcrypt, non-empty)."""


class UsernameOutOfBoundsError(AuthError):
    """Username failed field-level bounds."""


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    exp: datetime
    iat: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": str(self.user_id),
            "exp": int(self.exp.timestamp()),
            "iat": int(self.iat.timestamp()),
        }


def hash_password(password: str) -> str:
    """Hash `password` at cost 12. bcrypt limits input to 72 bytes; longer
    passwords raise `WeakPasswordError`."""
    pw_bytes = password.encode("utf-8")
    if not pw_bytes:
        raise WeakPasswordError("password must not be empty")
    if len(pw_bytes) > 72:
        # bcrypt silently truncates past 72 bytes, which would let two
        # distinct long passwords match. Reject loudly instead.
        raise WeakPasswordError("password must be ≤ 72 bytes (bcrypt limit)")
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time compare. `InvalidCredentialsError` is raised on mismatch
    — the caller decides whether to log or surface."""
    try:
        ok = bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed hash: treat as wrong password (don't leak format errors).
        return False
    if not ok:
        return False
    return True


def create_token(
    user_id: uuid.UUID,
    *,
    secret: str,
    algorithm: str = "HS256",
    ttl_seconds: int = DEFAULT_JWT_TTL,
    now: datetime | None = None,
) -> tuple[str, TokenClaims]:
    """Mint a JWT carrying `user_id` and `exp`. Returns (token, claims)."""
    issued = now or datetime.now(timezone.utc)
    expires = issued + timedelta(seconds=ttl_seconds)
    claims = TokenClaims(user_id=user_id, exp=expires, iat=issued)
    token = jwt.encode(claims.to_dict(), secret, algorithm=algorithm)
    return token, claims


def decode_token(token: str, *, secret: str, algorithm: str = "HS256") -> TokenClaims:
    """Decode and validate a JWT. Raises `InvalidTokenError` on any failure."""
    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise InvalidTokenError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError(f"invalid token: {exc}") from exc

    user_id_str = payload.get("user_id")
    exp = payload.get("exp")
    if not user_id_str or exp is None:
        raise InvalidTokenError("token missing required claims")

    try:
        user_id = uuid.UUID(str(user_id_str))
        exp_dt = datetime.fromtimestamp(int(exp), tz=timezone.utc)
    except (ValueError, TypeError) as exc:
        raise InvalidTokenError(f"malformed claim: {exc}") from exc

    return TokenClaims(user_id=user_id, exp=exp_dt, iat=datetime.fromtimestamp(int(payload.get("iat", exp - 1)), tz=timezone.utc))


def sha256_hex(token: str) -> str:
    """SHA-256 hex digest of the bearer token (for the blacklist PK)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_username(username: str) -> str:
    """Enforce field-level bounds; reject empty / oversize values."""
    if not isinstance(username, str):
        raise UsernameOutOfBoundsError("username must be a string")
    stripped = username.strip()
    if not stripped:
        raise UsernameOutOfBoundsError("username must not be empty")
    if len(stripped) > 255:
        raise UsernameOutOfBoundsError("username must be ≤ 255 chars")
    return stripped