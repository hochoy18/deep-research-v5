"""Migration tests.

Verifies the initial Alembic migration:
  - applies cleanly against an empty database
  - creates the expected `users` and `auth_token_blacklist` tables
  - re-applies idempotently (the migration script itself is forward-only;
    `alembic upgrade head` against an already-current DB is a no-op)

Alembic tracks current state in `alembic_version`; running `upgrade head`
on a fresh DB inserts one row, and a second run leaves it alone.
"""

from __future__ import annotations

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, inspect, text

# `sqlite_url` and `alembic_config` live in this directory's conftest.


class TestInitialMigration:
    def test_upgrade_applies_cleanly(self, alembic_config, sqlite_url: str) -> None:
        command.upgrade(alembic_config, "head")

        engine = create_engine(sqlite_url)
        with engine.connect() as conn:
            tables = set(inspect(conn).get_table_names())
        assert {"users", "auth_token_blacklist"}.issubset(tables)
        assert "alembic_version" in tables

    def test_upgrade_is_idempotent(self, alembic_config, sqlite_url: str) -> None:
        """Running the same upgrade twice must not error or duplicate."""
        command.upgrade(alembic_config, "head")

        engine = create_engine(sqlite_url)
        with engine.connect() as conn:
            tables_after_first = set(inspect(conn).get_table_names())

        # Second run — should be a no-op.
        command.upgrade(alembic_config, "head")

        with engine.connect() as conn:
            tables_after_second = set(inspect(conn).get_table_names())
        assert tables_after_first == tables_after_second

    def test_users_table_has_unique_username(
        self, alembic_config, sqlite_url: str
    ) -> None:
        command.upgrade(alembic_config, "head")
        engine = create_engine(sqlite_url)
        with engine.connect() as conn:
            unique = inspect(conn).get_unique_constraints("users")
        assert any(c["column_names"] == ["username"] for c in unique)

    def test_auth_token_blacklist_has_token_hash_pk(
        self, alembic_config, sqlite_url: str
    ) -> None:
        command.upgrade(alembic_config, "head")
        engine = create_engine(sqlite_url)
        with engine.connect() as conn:
            pk = inspect(conn).get_pk_constraint("auth_token_blacklist")
        assert "token_hash" in pk["constrained_columns"]

    def test_auth_token_blacklist_fk_to_users(
        self, alembic_config, sqlite_url: str
    ) -> None:
        command.upgrade(alembic_config, "head")
        engine = create_engine(sqlite_url)
        with engine.connect() as conn:
            fks = inspect(conn).get_foreign_keys("auth_token_blacklist")
        user_fks = [fk for fk in fks if fk["referred_table"] == "users"]
        assert user_fks, "no FK from auth_token_blacklist → users"
        assert "user_id" in user_fks[0]["constrained_columns"]

    def test_columns_have_expected_types(
        self, alembic_config, sqlite_url: str
    ) -> None:
        command.upgrade(alembic_config, "head")
        engine = create_engine(sqlite_url)
        with engine.connect() as conn:
            users_cols = {c["name"]: c for c in inspect(conn).get_columns("users")}
            bl_cols = {c["name"]: c for c in inspect(conn).get_columns("auth_token_blacklist")}

        assert set(users_cols) == {"id", "username", "password_hash", "created_at"}
        assert set(bl_cols) == {"token_hash", "user_id", "expires_at", "created_at"}

        # VARCHAR-style lengths are stored as the type's `length`.
        assert users_cols["username"]["type"].length == 255
        assert users_cols["password_hash"]["type"].length == 255
        assert bl_cols["token_hash"]["type"].length == 64

    def test_downgrade_removes_tables(self, alembic_config, sqlite_url: str) -> None:
        command.upgrade(alembic_config, "head")
        command.downgrade(alembic_config, "base")
        engine = create_engine(sqlite_url)
        with engine.connect() as conn:
            tables = set(inspect(conn).get_table_names())
        # `users` and `auth_token_blacklist` are gone; only alembic bookkeeping
        # (or nothing) remains.
        assert "users" not in tables
        assert "auth_token_blacklist" not in tables

    def test_alembic_version_matches_revision(
        self, alembic_config, sqlite_url: str
    ) -> None:
        command.upgrade(alembic_config, "head")
        engine = create_engine(sqlite_url)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == "0002_plan_tables"