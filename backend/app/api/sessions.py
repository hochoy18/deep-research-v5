"""FastAPI router for the `/sessions*` endpoints.

Issue #3 delivers the first three of the six session endpoints:

  POST /sessions                  → 201 {session_id} — runs plan_generate
                                    and parks the graph on `plan_wait_human`
  GET  /sessions/{id}/events      → SSE; replays `plan_ready` to a browser
                                    that connects after the POST
  GET  /sessions/{id}/state       → the current Plan, so a refreshing page
                                    renders without waiting for an event

The other three (`plan/edit`, `plan/approve`, `report`) belong to issues
#4 and #7.

Every endpoint requires a valid bearer and is scoped to the caller's own
Conversations: a Session that belongs to someone else reads as 404, never
as 403, so a response cannot confirm that another user's id exists.

`POST /sessions` is deliberately synchronous through `plan_generate`:
that is what lets a model refusal answer 422 with the model's reason
instead of failing later on a stream the user is watching.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DbSession

from ..auth.deps import get_current_user
from ..db.models import User
from ..db.session import get_db
from ..plan.graph import start_session
from ..plan.schemas import PlanValidationError
from ..plan.service import PlanRefusedError, PlanService
from ..seams.call_llm import LLMNotConfiguredError
from ..seams.stream_event import events_since, latest_event_id, subscribe
from .schemas import (
    CreateSessionRequest,
    CreateSessionResponse,
    PlanOut,
    SessionOut,
    SessionStateResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])

# How long the SSE endpoint waits between polls of its subscriber queue.
_POLL_SECONDS = 0.05


def _owned_session(service: PlanService, session_id: uuid.UUID, user: User):
    """The caller's Conversation, or 404."""
    conversation = service.conversation_for(session_id, user.id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return conversation


def _plan_rejected(exc: Exception, violations: list[dict[str, str]]) -> HTTPException:
    """The 422 both ways `plan_generate` can fail share.

    `reason` is the one sentence the frontend shows the user, so for a
    refusal it is the model's own words and for a schema violation it is a
    summary of the field paths. `violations` is populated only for the
    latter — a refusal carries no field paths.
    """
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "reason": getattr(exc, "reason", str(exc)),
            "stage": "plan_generate",
            "violations": violations,
        },
    )


@router.post("", response_model=CreateSessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    body: CreateSessionRequest,
    user: User = Depends(get_current_user),
) -> CreateSessionResponse:
    """Start a Session: persist the Query, generate the Plan, wait for HITL."""
    session_id = uuid.uuid4()

    try:
        start_session(session_id, user.id, body.query)
    except PlanRefusedError as exc:
        # The node's transaction rolled back, so there is no half-created
        # Session behind this 422 — the user simply has to rephrase.
        raise _plan_rejected(exc, []) from exc
    except PlanValidationError as exc:
        raise _plan_rejected(exc, exc.as_payload()) from exc
    except LLMNotConfiguredError as exc:
        # Not the caller's fault and not the Query's: the deployment cannot
        # reach a model. 503 rather than 500 says "this is temporarily
        # unavailable", and the detail names the operator action, so an
        # unconfigured dev box reports what is missing instead of an
        # anonymous stack trace.
        logger.error("plan_generate is not configured: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "reason": "plan generation is not available on this server",
                "detail": str(exc),
                "stage": "plan_generate",
            },
        ) from exc

    return CreateSessionResponse(session_id=session_id)


@router.get("/{session_id}/events")
def session_events(
    session_id: uuid.UUID,
    request: Request,
    last_event_id: str | None = Query(default=None, alias="last_event_id"),
    timeout: float | None = Query(default=None, gt=0, le=300),
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> StreamingResponse:
    """SSE stream of a Session's events.

    Replays everything after `last_event_id` (or the whole Session when
    the client sends none) before streaming live, so a browser that
    connects after `POST /sessions` still receives the `plan_ready` it
    missed. `timeout` closes the stream after N seconds; it exists so a
    test can assert on the replay without hanging on an idle Session.
    """
    _owned_session(PlanService(db), session_id, user)
    after = _parse_last_event_id(request, last_event_id)
    stream = _event_stream(str(session_id), after, timeout, request)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{session_id}/state", response_model=SessionStateResponse)
def session_state(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> SessionStateResponse:
    """The current snapshot: Conversation, latest Plan, report if any."""
    service = PlanService(db)
    conversation = _owned_session(service, session_id, user)

    row = service.latest_plan(conversation.id)
    plan = PlanOut.from_domain(service.plan_to_domain(row), plan_id=row.id) if row else None

    return SessionStateResponse(
        session=SessionOut(
            session_id=conversation.id,
            query=conversation.query,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        ),
        plan=plan,
        report_md=conversation.report_md,
        latest_event_id=latest_event_id(str(conversation.id)),
    )


# --- SSE plumbing ----------------------------------------------------------


def _parse_last_event_id(request: Request, query_value: str | None) -> int:
    """`Last-Event-ID` header first, query parameter second."""
    raw = request.headers.get("last-event-id") or query_value or "0"
    try:
        return max(int(raw), 0)
    except (TypeError, ValueError):
        return 0


async def _event_stream(
    session_id: str,
    after_id: int,
    timeout: float | None,
    request: Request,
) -> AsyncIterator[str]:
    """Replay, then follow, as SSE frames.

    Subscribe first, replay second, skip anything already replayed: that
    ordering is what makes the handover gap-free.
    """
    loop = asyncio.get_running_loop()
    deadline = None if timeout is None else loop.time() + timeout

    with subscribe(session_id) as subscriber:
        for event in events_since(session_id, after_id):
            after_id = max(after_id, event["id"])
            yield _sse_frame(event)

        while True:
            if await request.is_disconnected():
                return
            if deadline is not None and loop.time() >= deadline:
                return
            try:
                event = await asyncio.to_thread(subscriber.get, True, _POLL_SECONDS)
            except Exception:
                continue  # empty poll: re-check the clock and the client
            if event["id"] <= after_id:
                continue  # already replayed
            after_id = event["id"]
            yield _sse_frame(event)


def _sse_frame(event: dict) -> str:
    """One SSE frame. `id:` is what `Last-Event-ID` sends back."""
    return f"id: {event['id']}\nevent: {event['event']}\ndata: {json.dumps(event['data'], default=str)}\n\n"