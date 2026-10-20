"""initial schema: users + auth_token_blacklist

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-20 00:00:00

This is the only P1 schema. It creates the two tables required by the auth
ticket (issue #2). Later tickets add `conversations`, `messages`, and
`plans` per `docs/milestones.md` "app_db" section.

The migration is **idempotent in the sense that running it twice on a fresh
database is safe** (Postgres CREATE TABLE, then a no-op `alembic upgrade`),
but it is forward-only: once committed, downgrades are for debugging only.

UUID columns are typed via the shared `GUID` type so the migration works
against both production Postgres (native UUID) and the test SQLite
(string-stored UUID).
"""

from __future__ import annotations

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Build a portable UUID column for both dialects. Postgres gets the native
# type (efficient + 16 bytes); SQLite stores it as a 36-char string.
def _uuid_column() -> sa.types.TypeEngine:
    if op.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import UUID

        return UUID(as_uuid=True)
    return sa.String(length=36)


def upgrade() -> None:
    uuid_t = _uuid_column()
    is_postgres = op.get_bind().dialect.name == "postgresql"
    default_now = sa.text("now()" if is_postgres else "CURRENT_TIMESTAMP")

    # users
    op.create_table(
        "users",
        sa.Column("id", uuid_t, primary_key=True),
        sa.Column("username", sa.String(length=255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=default_now,
            nullable=False,
        ),
    )

    # auth_token_blacklist
    op.create_table(
        "auth_token_blacklist",
        sa.Column("token_hash", sa.String(length=64), primary_key=True),
        sa.Column(
            "user_id",
            uuid_t,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=default_now,
            nullable=False,
        ),
    )
    op.create_index(
        "ix_auth_token_blacklist_user_id",
        "auth_token_blacklist",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_auth_token_blacklist_user_id", table_name="auth_token_blacklist")
    op.drop_table("auth_token_blacklist")
    op.drop_table("users")