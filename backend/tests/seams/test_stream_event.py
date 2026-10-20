"""Behavior tests for the stream_event seam."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models import Message
from app.seams.stream_event import StreamEventError, get_buffer, reset_buffer, stream_event


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_buffer()


class TestStreamEvent:
    def test_event_recorded_with_session_id(self) -> None:
        stream_event("plan_ready", {"session_id": "s1", "plan": {}})
        buf = get_buffer("s1")
        assert len(buf) == 1
        assert buf[0]["event"] == "plan_ready"
        assert buf[0]["data"]["session_id"] == "s1"
        assert isinstance(buf[0]["id"], int)

    def test_event_ids_are_monotonic_within_session(self) -> None:
        stream_event("plan_ready", {"session_id": "s1"})
        stream_event("research_progress", {"session_id": "s1"})
        stream_event("report_ready", {"session_id": "s1"})
        buf = get_buffer("s1")
        ids = [e["id"] for e in buf]
        assert ids == sorted(ids)
        assert len(set(ids)) == 3

    def test_sessions_are_isolated(self) -> None:
        stream_event("plan_ready", {"session_id": "s1"})
        stream_event("plan_ready", {"session_id": "s2"})
        assert len(get_buffer("s1")) == 1
        assert len(get_buffer("s2")) == 1

    def test_missing_session_id_routes_to_unscoped(self) -> None:
        stream_event("error", {"reason": "boom"})
        assert get_buffer("s1") == []
        assert len(get_buffer("_unscoped")) == 1

    def test_empty_session_id_routes_to_unscoped(self) -> None:
        stream_event("error", {"session_id": "", "reason": "boom"})
        assert len(get_buffer("_unscoped")) == 1

    def test_non_dict_payload_rejected(self) -> None:
        with pytest.raises(StreamEventError):
            stream_event("plan_ready", "not a dict")  # type: ignore[arg-type]

    def test_reset_clears_buffer(self) -> None:
        stream_event("plan_ready", {"session_id": "s1"})
        reset_buffer("s1")
        assert get_buffer("s1") == []


class TestPersistence:
    """Only a real Conversation can become a `messages` row. Buffering keys
    off whatever the caller passes, so a synthetic id has to be delivered
    without a dangling foreign key."""

    def test_uuid_key_is_persisted(self, db_session) -> None:
        conversation_id = uuid.uuid4()
        stream_event("plan_ready", {"session_id": str(conversation_id)})

        rows = db_session.execute(select(Message)).scalars().all()

        assert [m.conversation_id for m in rows] == [conversation_id]
        assert rows[0].role == "event"
        assert rows[0].event_type == "plan_ready"

    def test_synthetic_key_is_buffered_but_not_persisted(self, db_session) -> None:
        stream_event("plan_ready", {"session_id": "s1"})

        assert len(get_buffer("s1")) == 1
        assert db_session.execute(select(Message)).scalars().all() == []