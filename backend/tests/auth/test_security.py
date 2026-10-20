"""Unit tests for the password / JWT helpers."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.security import (
    BCRYPT_ROUNDS,
    DuplicateUserError,
    InvalidTokenError,
    TokenClaims,
    WeakPasswordError,
    create_token,
    decode_token,
    hash_password,
    sha256_hex,
    verify_password,
)


SECRET = "test-secret"


class TestPassword:
    def test_hash_round_trip(self) -> None:
        h = hash_password("hunter2")
        assert verify_password("hunter2", h) is True

    def test_wrong_password_rejected(self) -> None:
        h = hash_password("hunter2")
        assert verify_password("hunter3", h) is False

    def test_empty_password_rejected(self) -> None:
        with pytest.raises(WeakPasswordError):
            hash_password("")

    def test_overlong_password_rejected(self) -> None:
        # bcrypt silently truncates >72 bytes; we reject loudly instead.
        with pytest.raises(WeakPasswordError):
            hash_password("a" * 73)

    def test_hash_format_is_bcrypt(self) -> None:
        h = hash_password("hunter2")
        # bcrypt format: $2[abxy]$<cost>:<22-char-salt><31-char-hash>
        # Different bcrypt versions emit slightly different version tags;
        # we accept any of the standard prefixes.
        prefix = h.split(":", 1)[0]
        assert prefix.startswith("$2")
        cost = prefix.split("$")[2]
        assert cost == str(BCRYPT_ROUNDS)

    def test_hashes_are_unique(self) -> None:
        a = hash_password("hunter2")
        b = hash_password("hunter2")
        assert a != b  # different salts

    def test_malformed_hash_returns_false(self) -> None:
        # `verify_password` must never raise on a bad stored hash.
        assert verify_password("hunter2", "not-a-bcrypt-hash") is False


class TestToken:
    def test_round_trip(self) -> None:
        uid = uuid.uuid4()
        token, claims = create_token(uid, secret=SECRET)
        decoded = decode_token(token, secret=SECRET)
        assert decoded.user_id == uid
        assert isinstance(decoded, TokenClaims)

    def test_24_hour_default_ttl(self) -> None:
        uid = uuid.uuid4()
        before = datetime.now(timezone.utc)
        _, claims = create_token(uid, secret=SECRET)
        delta = claims.exp - before
        # Allow a few seconds of drift in either direction.
        assert timedelta(seconds=24 * 3600 - 5) < delta < timedelta(seconds=24 * 3600 + 5)

    def test_custom_ttl(self) -> None:
        uid = uuid.uuid4()
        _, claims = create_token(uid, secret=SECRET, ttl_seconds=60)
        delta = claims.exp - datetime.now(timezone.utc)
        assert timedelta(seconds=55) < delta < timedelta(seconds=65)

    def test_wrong_secret_rejected(self) -> None:
        token, _ = create_token(uuid.uuid4(), secret="a")
        with pytest.raises(InvalidTokenError):
            decode_token(token, secret="b")

    def test_expired_token_rejected(self) -> None:
        uid = uuid.uuid4()
        token, _ = create_token(uid, secret=SECRET, ttl_seconds=-1)
        time.sleep(0.01)
        with pytest.raises(InvalidTokenError) as exc:
            decode_token(token, secret=SECRET)
        assert "expired" in str(exc.value).lower()

    def test_algorithm_pinned(self) -> None:
        token, _ = create_token(uuid.uuid4(), secret=SECRET, algorithm="HS256")
        # Trying to verify with a different algorithm must fail.
        with pytest.raises(InvalidTokenError):
            decode_token(token, secret=SECRET, algorithm="HS512")

    def test_token_claims_include_user_id_and_exp(self) -> None:
        uid = uuid.uuid4()
        token, claims = create_token(uid, secret=SECRET)
        decoded = decode_token(token, secret=SECRET)
        assert decoded.user_id == uid
        # JWT encodes `exp` as an integer second; sub-second precision is
        # lost on round-trip, so compare within 1 second.
        assert abs((decoded.exp - claims.exp).total_seconds()) < 1


class TestSha256:
    def test_deterministic(self) -> None:
        a = sha256_hex("hello")
        b = sha256_hex("hello")
        assert a == b
        assert len(a) == 64

    def test_distinct_inputs_distinct_hashes(self) -> None:
        assert sha256_hex("a") != sha256_hex("b")