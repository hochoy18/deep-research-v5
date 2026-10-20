"""Behaviour tests for the Plan Layer's graph.

The one thing the whole vertical slice rests on is that the run *stops*:
`plan_wait_human` must interrupt, leaving the graph parked awaiting HITL
with a Plan on disk and nothing executing behind it. If `interrupt()`
silently no-op'd, every HTTP test would still pass — the Plan would be
written and 201 returned — so the interrupt itself is asserted here.

Per issue #1 §3 these tests substitute the `call_llm` seam, exactly as
the HTTP layer does, and assert on graph state rather than internals.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models import Conversation, PlanRow
from app.plan.graph import WAITING_FOR_REVIEW, get_graph, graph_config, start_session
from app.seams.stream_event import get_buffer, reset_buffer


@pytest.fixture
def stub_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    def _stub(*_: object, **__: object) -> str:
        return (
            '{"sections": [{"title": "Background", "brief": "Where it came from.",'
            ' "sub_questions": ["When did it start?"], "note": null}],'
            ' "plan_note": null}'
        )

    monkeypatch.setattr("app.plan.service.call_llm", _stub)


@pytest.fixture
def actor(settings) -> tuple[uuid.UUID, uuid.UUID]:
    """A user id and a session id, without needing a real signup."""
    return uuid.uuid4(), uuid.uuid4()


def test_the_run_parks_on_plan_wait_human(stub_llm, actor, db_session) -> None:
    """The spec's acceptance criterion, asserted directly."""
    user_id, conversation_id = actor

    result = start_session(conversation_id, user_id, "why is the sky blue?")

    # LangGraph surfaces the interrupt in its output state.
    interrupts = result.get("__interrupt__") or []
    assert len(interrupts) == 1, f"expected one interrupt, got {result!r}"
    assert interrupts[0].value["stage"] == WAITING_FOR_REVIEW
    assert interrupts[0].value["conversation_id"] == str(conversation_id)
    assert interrupts[0].value["plan_version"] == 1


def test_the_parked_run_is_still_parked_when_read_back(stub_llm, actor) -> None:
    """A checkpoint exists, so resuming later (issue #4) continues this run
    rather than starting a new one."""
    user_id, conversation_id = actor
    start_session(conversation_id, user_id, "why?")

    snapshot = get_graph().get_state(graph_config(conversation_id))

    assert snapshot.next == ("plan_wait_human",)
    assert snapshot.interrupts, "the checkpoint records no interrupt"


def test_research_does_not_run_before_the_human_decides(stub_llm, actor, db_session) -> None:
    """Nothing beyond the Plan exists: one Conversation, one Plan row, and
    no second revision written behind the user's back."""
    user_id, conversation_id = actor

    start_session(conversation_id, user_id, "why?")

    assert db_session.execute(select(Conversation)).scalars().all() != []
    plans = db_session.execute(
        select(PlanRow).where(PlanRow.conversation_id == conversation_id)
    ).scalars().all()
    assert [p.version for p in plans] == [1]
    assert all(p.approved is False for p in plans)


def test_the_plan_is_announced_before_the_interrupt(stub_llm, actor) -> None:
    """`plan_ready` is emitted while the node runs, so it is already in the
    buffer by the time the graph parks."""
    reset_buffer()
    user_id, conversation_id = actor

    start_session(conversation_id, user_id, "why?")

    events = get_buffer(str(conversation_id))
    assert [e["event"] for e in events] == ["plan_ready"]
    assert events[0]["data"]["plan"]["sections"][0]["title"] == "Background"