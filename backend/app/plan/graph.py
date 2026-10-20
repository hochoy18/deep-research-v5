"""The Plan Layer's LangGraph.

```
START → plan_generate(query)              # call_llm → validate → persist plans row
       → stream_event('plan_ready')       # the UI can render
       → plan_wait_human   ── interrupt ──┐   # waits for HITL (issue #4)
                                          │
       ┌──────────────────────────────────┘   # on resume: approved=true in place
       └→ research … (issue #5)
```

Issue #3 ships the first two nodes. `plan_wait_human` interrupts and the
run parks there, which is exactly the state the user sees on the Plan
page: a Plan to read, nothing running behind it.

One transaction per node: `plan_generate` opens the Conversation, writes
the user's Message, generates the Plan, and writes the `plans` row
together. A refused Query therefore rolls all of it back — a 422 leaves
no Session, no transcript entry, no orphan Plan. That is why the API
allocates `conversation_id` up front and the node persists it.

Nodes never receive a request-scoped `Session`: LangGraph resumes across
requests (and across processes), so each node opens its own.
"""

from __future__ import annotations

import logging
import uuid

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, StateGraph
from langgraph.types import interrupt

from ..db.session import session_scope
from ..seams.stream_event import stream_event
from ..state.plan import SessionState
from .service import PlanService

logger = logging.getLogger(__name__)

WAITING_FOR_REVIEW = "awaiting_plan_review"

# The process-level checkpointer. `thread_id` is the Session UUID, so a
# run's checkpoints are keyed by the same id the API hands the user.
# Issue #9 swaps this for the Postgres checkpointer; the graph code does
# not change.
_checkpointer = InMemorySaver()


def plan_generate(state: SessionState) -> dict[str, object]:
    """Query → Structured Plan → `plans` row → `plan_ready` event.

    Raises `PlanRefusedError` / `PlanValidationError`; either way the
    transaction rolls back and the API answers 422.
    """
    conversation_id = uuid.UUID(str(state["conversation_id"]))
    user_id = uuid.UUID(str(state["user_id"]))
    query = str(state["query"])

    with session_scope() as session:
        service = PlanService(session)
        service.open_conversation(conversation_id, user_id, query)
        plan = service.generate(query)
        row = service.persist_first_revision(conversation_id, plan)
        # Read the row's own values before the transaction closes: after
        # commit the instance is detached and its attributes expired.
        plan_id = str(row.id)
        plan_version = row.version
        approved = row.approved

    plan_payload = plan.model_dump(mode="json")
    stream_event(
        "plan_ready",
        {
            # One id, one name: `session_id` is the API-facing term (see
            # CONTEXT.md, Session ↔ Conversation 1:1). The seam accepts
            # either key so a caller holding a Conversation row can pass it.
            "session_id": str(conversation_id),
            "plan_id": plan_id,
            "plan_version": plan_version,
            "approved": approved,
            "plan": plan_payload,
        },
    )

    return {
        "plan": plan_payload,
        "plan_id": plan_id,
        "plan_version": plan_version,
        "approved": approved,
    }


def plan_wait_human(state: SessionState) -> dict[str, object]:
    """Park the run until the user acts on the Plan.

    `interrupt()` suspends here and the graph returns to the API with a
    resume token. Issue #4 resumes from here: it applies the HITL
    operation to the `plans` rows, then resumes with `Command(resume=...)`
    once `approved` is true.
    """
    interrupt(
        {
            "stage": WAITING_FOR_REVIEW,
            "conversation_id": state["conversation_id"],
            "plan_version": state.get("plan_version", 1),
        }
    )
    # Only reached after a resume; the Research layer continues from here.
    return {}


_compiled = None


def get_graph():
    """The compiled Plan graph, built once per process."""
    global _compiled
    if _compiled is None:
        builder = StateGraph(SessionState)
        builder.add_node("plan_generate", plan_generate)
        builder.add_node("plan_wait_human", plan_wait_human)
        builder.add_edge(START, "plan_generate")
        builder.add_edge("plan_generate", "plan_wait_human")
        _compiled = builder.compile(checkpointer=_checkpointer)
    return _compiled


def graph_config(conversation_id: uuid.UUID) -> dict[str, dict[str, str]]:
    """LangGraph invocation config. `thread_id` is the Session UUID."""
    return {"configurable": {"thread_id": str(conversation_id)}}


def start_session(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    query: str,
) -> dict:
    """Run the graph from START until it interrupts.

    Returns the graph's output state; the caller has already received
    `plan_ready` over SSE by the time this returns.
    """
    return get_graph().invoke(
        {
            "conversation_id": str(conversation_id),
            "user_id": str(user_id),
            "query": query,
        },
        config=graph_config(conversation_id),
    )


__all__ = [
    "WAITING_FOR_REVIEW",
    "get_graph",
    "graph_config",
    "plan_generate",
    "plan_wait_human",
    "start_session",
]