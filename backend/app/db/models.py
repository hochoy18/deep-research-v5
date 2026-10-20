"""ORM models.

`User` + `AuthTokenBlacklist` came with issue #2; `Conversation`,
`Message`, and `PlanRow` with issue #3. Column-level DDL is fixed by
`docs/milestones.md` "Database schema (app_db)" and is mirrored by the
Alembic migrations — change both together or neither.

`PlanRow` is named for what it is: the persisted form of a Plan
revision. The domain object the Plan layer passes around is
`app.plan.schemas.Plan`; the two are deliberately different types so a
half-populated ORM row can never masquerade as a validated Plan.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import GUID, Base, TimestampMixin

# JSONB on Postgres (indexable, compact), plain JSON elsewhere so the
# SQLite test database behaves identically.
JSONVariant = JSON().with_variant(postgresql.JSONB(), "postgresql")


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


class Conversation(Base, TimestampMixin):
    """One Session's durable record.

    `Session` (API term) and `Conversation` (persistence term) are the
    same UUID. `report_md` stays NULL until the Write layer finishes
    (issue #7); `updated_at` is the anchor for the 30-day retention
    clock in issue #11.
    """

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    query: Mapped[str] = mapped_column(Text(), nullable=False)
    report_md: Mapped[str | None] = mapped_column(Text(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(lazy="joined")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    plans: Mapped[list["PlanRow"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base, TimestampMixin):
    """One entry in a Conversation's transcript.

    `role` is `'user'` for what the user typed, `'system'` for internal
    notes, `'event'` for one streamed UI event. Event rows carry
    `event_type` (`plan_ready`, ...) and the JSON event body in
    `content`, which is what makes the SSE stream replayable by
    `Last-Event-ID` in issue #9.
    """

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str | None] = mapped_column(Text(), nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(64), nullable=True)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class PlanRow(Base, TimestampMixin):
    """One Plan revision.

    Revisions are append-only: every HITL edit (issue #4) writes a new row
    with `version + 1`. The one exception is Approve, which flips
    `approved` / `approved_at` in place, because the running graph holds
    a reference to the row it is executing against.

    `sections` holds the validated Plan JSON. `plan_note` is never written
    in P1 — a Plan-level Note is a P2 feature (issue #4 notes are
    per-Section and live inside `sections`).
    """

    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, nullable=False)
    plan_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    approved: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=False, server_default=text("false")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="plans")