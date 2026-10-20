"""plan tables: conversations + messages + plans

Revision ID: 0002_plan_tables
Revises: 0001_initial
Create Date: 2026-10-20 13:10:00

Issue #3 is where these three tables are born. DDL is fixed by
`docs/milestones.md` "Database schema (app_db)":

  conversations  one row per Session (`Session` and `Conversation` are the
                 same UUID — one is the API term, one the persistence term)
  messages       the user's Query as `role='user'`, plus one row per SSE
                 event (`role='event'`, carrying `event_type`)
  plans          one row per Plan revision; issue #3 writes version=1,
                 issue #4 appends `version + 1` per HITL edit

`plans.sections` is JSONB on Postgres (indexable, compact) and plain JSON
elsewhere so the SQLite test database behaves the same.

Forward-only, per the P1 spec: P2 and P3 add columns and tables, nothing
here is dropped or narrowed.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_plan_tables"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_column() -> sa.types.TypeEngine:
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.String(length=36)


def _json_column() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    uuid_t = _uuid_column()
    json_t = _json_column()
    is_postgres = op.get_bind().dialect.name == "postgresql"
    default_now = sa.text("now()" if is_postgres else "CURRENT_TIMESTAMP")

    op.create_table(
        "conversations",
        sa.Column("id", uuid_t, primary_key=True),
        sa.Column(
            "user_id",
            uuid_t,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("report_md", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=default_now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=default_now, nullable=False),
    )

    op.create_table(
        "messages",
        sa.Column("id", uuid_t, primary_key=True),
        sa.Column(
            "conversation_id",
            uuid_t,
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=default_now, nullable=False),
    )

    op.create_table(
        "plans",
        sa.Column("id", uuid_t, primary_key=True),
        sa.Column(
            "conversation_id",
            uuid_t,
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sections", json_t, nullable=False),
        sa.Column("plan_note", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "approved",
            sa.Boolean(),
            server_default=sa.text("false" if is_postgres else "0"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=default_now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=default_now, nullable=False),
    )

    # The only two non-PK indexes in the project (issue #1 §5): latest Plan
    # revision in one query, and retention sweeps per user.
    op.create_index(
        "ix_conversations_user_id_updated_at",
        "conversations",
        ["user_id", "updated_at"],
    )
    op.create_index(
        "ix_plans_conversation_id_version",
        "plans",
        ["conversation_id", "version"],
    )


def downgrade() -> None:
    op.drop_index("ix_plans_conversation_id_version", table_name="plans")
    op.drop_index("ix_conversations_user_id_updated_at", table_name="conversations")
    op.drop_table("plans")
    op.drop_table("messages")
    op.drop_table("conversations")