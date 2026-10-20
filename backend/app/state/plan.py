"""LangGraph state — the coordination seam between layers.

Per issue #1 §1 the three layers never import each other; they coordinate
through this state object and the five seams. State values are plain
JSON types on purpose: LangGraph checkpoints serialise them, and a
SQLAlchemy `Session` or an open HTTP connection would not survive a
resume (issue #9).

PostgreSQL remains the source of truth. Nothing durable lives only in
graph state: nodes read the latest `plans` row, so a process restart
loses nothing but the in-flight interrupt.
"""

from __future__ import annotations

from typing import Any, TypedDict


class SessionState(TypedDict, total=False):
    """State carried through the graph, one Session's run.

    Keys
    ----
    conversation_id:
        The Session UUID, allocated by the API before the run starts.
        Doubles as the LangGraph `thread_id`.
    user_id:
        The owner, from the JWT. Scopes every read.
    query:
        The User Query, verbatim.
    plan:
        The validated Plan as JSON (`{sections: [...], ...}`), written by
        `plan_generate` and refreshed by the HITL operations (issue #4).
    plan_id / plan_version:
        The `plans` row this run is executing against. Approve flips
        `approved` on that row in place.
    approved:
        The latch. False until the user approves; the Research layer
        (issue #5) refuses to start while it is False.
    """

    conversation_id: str
    user_id: str
    query: str
    plan: dict[str, Any]
    plan_id: str
    plan_version: int
    approved: bool