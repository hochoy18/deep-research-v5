"""ORM models.

P1 ships `User` and `AuthTokenBlacklist` only. `Conversation`, `Message`,
and `Plan` are reserved for later tickets per the P1 vertical slice in
`docs/milestones.md`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import GUID, Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)


class AuthTokenBlacklist(Base, TimestampMixin):
    __tablename__ = "auth_token_blacklist"

    # PK is the SHA-256 hex digest of the bearer token (64 chars). The PK
    # doubles as the natural lookup key on /auth/me and every /sessions*
    # request.
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    user: Mapped[User] = relationship(lazy="joined")