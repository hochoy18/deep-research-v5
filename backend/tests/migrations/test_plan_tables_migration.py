"""Tests for the `conversations` / `messages` / `plans` migration.

Issue #3 is where these three tables are born: one Conversation per
Session, the user's Query as a Message, and the first Plan revision.
The DDL is fixed by `docs/milestones.md` "Database schema (app_db)", so
these tests check the contract that the rest of the system depends on:

  - the three tables exist with the documented columns
  - conversations and plans are indexed the way the query patterns in
    issue #1 §5 describe (latest revision in one query; retention sweep)
  - a Plan's `sections` JSON round-trips through the column unchanged
"""

from __future__ import annotations

import json
import uuid

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, inspect, text


def _inspector(sqlite_url: str):
    engine = create_engine(sqlite_url)
    return engine, inspect(engine)


class TestSchema:
    def test_tables_are_created(self, alembic_config: AlembicConfig, sqlite_url: str) -> None:
        command.upgrade(alembic_config, "head")

        engine, insp = _inspector(sqlite_url)
        with engine.connect() as conn:
            tables = set(insp.get_table_names())

        assert {"conversations", "messages", "plans"}.issubset(tables)

    def test_conversations_columns(
        self, alembic_config: AlembicConfig, sqlite_url: str
    ) -> None:
        command.upgrade(alembic_config, "head")
        engine, insp = _inspector(sqlite_url)
        with engine.connect() as conn:
            cols = {c["name"]: c for c in insp.get_columns("conversations")}

        assert set(cols) == {"id", "user_id", "query", "report_md", "created_at", "updated_at"}
        assert cols["report_md"]["nullable"] is True  # null until the Write layer runs

    def test_messages_columns(
        self, alembic_config: AlembicConfig, sqlite_url: str
    ) -> None:
        command.upgrade(alembic_config, "head")
        engine, insp = _inspector(sqlite_url)
        with engine.connect() as conn:
            cols = {c["name"]: c for c in insp.get_columns("messages")}

        assert set(cols) == {
            "id",
            "conversation_id",
            "role",
            "content",
            "event_type",
            "created_at",
        }
        assert cols["event_type"]["nullable"] is True  # null for role='user' rows

    def test_plans_columns(
        self, alembic_config: AlembicConfig, sqlite_url: str
    ) -> None:
        command.upgrade(alembic_config, "head")
        engine, insp = _inspector(sqlite_url)
        with engine.connect() as conn:
            cols = {c["name"]: c for c in insp.get_columns("plans")}

        assert set(cols) == {
            "id",
            "conversation_id",
            "sections",
            "plan_note",
            "version",
            "approved",
            "approved_at",
            "created_at",
            "updated_at",
        }
        assert cols["plan_note"]["nullable"] is True  # Plan-level Note is P2
        assert cols["approved_at"]["nullable"] is True

    def test_version_is_not_nullable(self, alembic_config: AlembicConfig, sqlite_url: str) -> None:
        """`plans.version` orders revisions; a null one would break the
        `version DESC` read of the latest revision."""
        command.upgrade(alembic_config, "head")
        engine, insp = _inspector(sqlite_url)
        with engine.connect() as conn:
            cols = {c["name"]: c for c in insp.get_columns("plans")}
        assert cols["version"]["nullable"] is False

    def test_foreign_keys(self, alembic_config: AlembicConfig, sqlite_url: str) -> None:
        command.upgrade(alembic_config, "head")
        engine, insp = _inspector(sqlite_url)
        with engine.connect() as conn:
            conv_fk = insp.get_foreign_keys("conversations")
            msg_fk = insp.get_foreign_keys("messages")
            plan_fk = insp.get_foreign_keys("plans")

        assert [f["referred_table"] for f in conv_fk] == ["users"]
        assert [f["referred_table"] for f in msg_fk] == ["conversations"]
        assert [f["referred_table"] for f in plan_fk] == ["conversations"]

    def test_indexes_match_the_documented_query_patterns(
        self, alembic_config: AlembicConfig, sqlite_url: str
    ) -> None:
        """Issue #1 §5 allows exactly two non-PK indexes: latest Plan
        revision per conversation, and retention sweeps per user."""
        command.upgrade(alembic_config, "head")
        engine, insp = _inspector(sqlite_url)
        with engine.connect() as conn:
            conv_indexes = {
                idx["name"]: idx["column_names"] for idx in insp.get_indexes("conversations")
            }
            plan_indexes = {
                idx["name"]: idx["column_names"] for idx in insp.get_indexes("plans")
            }

        assert conv_indexes == {
            "ix_conversations_user_id_updated_at": ["user_id", "updated_at"]
        }
        assert plan_indexes == {
            "ix_plans_conversation_id_version": ["conversation_id", "version"]
        }


class TestStorage:
    def test_plan_sections_json_round_trips(
        self, alembic_config: AlembicConfig, sqlite_url: str
    ) -> None:
        command.upgrade(alembic_config, "head")
        engine = create_engine(sqlite_url)
        sections = [
            {
                "id": str(uuid.uuid4()),
                "title": "Background",
                "brief": "Where the topic came from.",
                "sub_questions": ["When did it start?"],
                "note": None,
            }
        ]

        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, username, password_hash) "
                    "VALUES (:id, 'alice', 'hash')"
                ),
                {"id": str(uuid.uuid4())},
            )
            user_id = conn.execute(text("SELECT id FROM users WHERE username='alice'")).scalar_one()
            conn.execute(
                text("INSERT INTO conversations (id, user_id, query) VALUES (:id, :u, :q)"),
                {"id": str(uuid.uuid4()), "u": user_id, "q": "why"},
            )
            conversation_id = conn.execute(text("SELECT id FROM conversations")).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO plans (id, conversation_id, sections, version, approved) "
                    "VALUES (:id, :c, :s, 1, 0)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "c": conversation_id,
                    "s": json.dumps(sections),
                },
            )
            stored = conn.execute(text("SELECT sections FROM plans")).scalar_one()

        assert json.loads(stored) == sections