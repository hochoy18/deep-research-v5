"""Seam: stream_event(event_type, payload) -> None

Single entry point for sending events to the frontend. Doing one thing
means doing both halves every time:

  1. append the event to `messages` (role='event') so the stream is
     replayable by `Last-Event-ID`, and
  2. push it to any live SSE subscriber on `GET /sessions/{id}/events`.

Both halves are best-effort in one direction only: persistence failing
must not silence an event that a browser is waiting on, so a failed write
is logged and the fan-out still happens. Conversely a subscriber's fate
is its own — a dead queue is dropped, never raised into the caller.

What "replayable" means today: `events_since()` reads this process's
in-memory log, not the `messages` rows. That covers the case the seam
exists for — a browser that connects after `POST /sessions`, or a dropped
connection reconnecting — and nothing more. A restart or a second worker
sees an empty log and `latest_event_id()` returns 0. Issue #9 reads the
persisted rows instead, which is what makes replay survive a restart.

Event ids are monotonic per process and carried in the `id:` field of the
SSE frame, which is what `Last-Event-ID` refers to.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import uuid
from collections import deque
from contextlib import contextmanager
from typing import Any, Iterator

from ..db.models import Message
from ..db.session import session_scope

logger = logging.getLogger(__name__)

# Event types in P1. Others are accepted (and logged) rather than rejected,
# so a later layer can ship without editing this file.
KNOWN_EVENTS = frozenset({"plan_ready", "research_progress", "report_ready", "error"})

_BUFFER_MAX = 10_000


class StreamEventError(RuntimeError):
    """Raised when stream_event cannot accept an event."""


class _Hub:
    """Per-session event log plus live subscriber queues.

    Queues are `queue.Queue` rather than `asyncio.Queue` because events
    are emitted from graph nodes running in a worker thread while the SSE
    endpoint drains them on the event loop. Consumers poll with a short
    interval, which is why the poll is documented rather than clever: P1
    emits a handful of events per Session.
    """

    def __init__(self) -> None:
        self.log: deque[dict[str, Any]] = deque(maxlen=_BUFFER_MAX)
        self.subscribers: list[queue.Queue[dict[str, Any]]] = []
        self.lock = threading.Lock()


_hubs: dict[str, _Hub] = {}
_event_counter = 0
_counter_lock = threading.Lock()


def _hub_for(session_id: str) -> _Hub:
    with _counter_lock:
        return _hubs.setdefault(session_id, _Hub())


def stream_event(event_type: str, payload: dict[str, Any]) -> None:
    """Record an event for SSE delivery.

    Parameters
    ----------
    event_type:
        One of `plan_ready`, `research_progress`, `report_ready`, `error`.
        Other values are accepted but logged as unknown.
    payload:
        Event body. `session_id` (equivalently `conversation_id`) scopes
        the event; everything else is passed through to the browser
        verbatim. `research_progress` carries `{section_index,
        total_sections, sources_count}`.

    Notes
    -----
    Non-blocking. The one loud error path is a non-dict `payload`, so a
    caller's mistake surfaces immediately instead of as a UI that
    mysteriously never updates.
    """
    if not isinstance(payload, dict):
        raise StreamEventError(f"payload must be a dict, got {type(payload).__name__}")

    session_key = _session_key_of(payload)
    event_id = _next_event_id()
    body = {**payload, "event_id": event_id}

    if event_type not in KNOWN_EVENTS:
        logger.info("stream_event: unknown event type %r", event_type)

    _persist(session_key, event_type, body)

    hub = _hub_for(session_key)
    with hub.lock:
        hub.log.append({"id": event_id, "event": event_type, "data": body})
        subscribers = list(hub.subscribers)
    for subscriber in subscribers:
        try:
            subscriber.put_nowait({"id": event_id, "event": event_type, "data": body})
        except queue.Full:  # pragma: no cover - unbounded queues do not fill
            logger.warning("dropping event %s for a saturated subscriber", event_id)


@contextmanager
def subscribe(session_id: str) -> Iterator[queue.Queue[dict[str, Any]]]:
    """Register a live subscriber for `session_id` for the block's duration.

    Callers replay from `events_since()` *after* entering the block, so
    an event published between replay and registration cannot be lost:
    anything that arrives on the queue with an id already replayed is
    skipped by the caller.
    """
    hub = _hub_for(session_id)
    subscriber: queue.Queue[dict[str, Any]] = queue.Queue()
    with hub.lock:
        hub.subscribers.append(subscriber)
    try:
        yield subscriber
    finally:
        with hub.lock:
            if subscriber in hub.subscribers:
                hub.subscribers.remove(subscriber)


def events_since(session_id: str, after_id: int = 0) -> list[dict[str, Any]]:
    """Recorded events with an id greater than `after_id`, in order.

    `after_id=0` replays the whole Session — what a browser that
    connected after `POST /sessions` needs in order to see the
    `plan_ready` it missed.
    """
    hub = _hub_for(session_id)
    with hub.lock:
        return [event for event in hub.log if event["id"] > after_id]


def latest_event_id(session_id: str) -> int:
    """The highest id recorded for this Session; 0 when nothing has been."""
    events = events_since(session_id)
    return events[-1]["id"] if events else 0


def get_buffer(session_id: str) -> list[dict[str, Any]]:
    """Test helper: return the recorded events for a session in order."""
    return events_since(session_id)


def reset_buffer(session_id: str | None = None) -> None:
    """Test helper: clear recorded events (all Sessions when omitted)."""
    global _event_counter
    with _counter_lock:
        if session_id is None:
            _hubs.clear()
            _event_counter = 0
        else:
            _hubs.pop(session_id, None)


# --- internals -------------------------------------------------------------


def _next_event_id() -> int:
    global _event_counter
    with _counter_lock:
        _event_counter += 1
        return _event_counter


def _session_key_of(payload: dict[str, Any]) -> str:
    """The Session this event belongs to.

    Any non-empty string is a usable key — the seam should not care
    whether a caller happens to have a UUID. Events without one are kept
    in a shared bucket rather than rejected, so a synthetic event from a
    unit test is neither silently dropped nor fatal.
    """
    for field in ("session_id", "conversation_id"):
        value = payload.get(field)
        if isinstance(value, uuid.UUID):
            return str(value)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "_unscoped"


def _persist(session_key: str, event_type: str, body: dict[str, Any]) -> None:
    """Write the event to `messages` so the stream can be replayed.

    Only a real Conversation UUID can be written — an event keyed by a
    synthetic id (a unit test, a dev tool) is delivered live and logged,
    but never becomes a row with a dangling foreign key.
    """
    try:
        conversation_id = uuid.UUID(session_key)
    except ValueError:
        return

    try:
        with session_scope() as session:
            session.add(
                Message(
                    id=uuid.uuid4(),
                    conversation_id=conversation_id,
                    role="event",
                    content=json.dumps(body, ensure_ascii=False, default=str),
                    event_type=event_type,
                )
            )
    except Exception as exc:
        # A browser waiting on this event is worse off than a missing
        # replay row; the failure is loud in the logs either way.
        logger.warning(
            "stream_event: could not persist %s for %s: %s", event_type, session_key, exc
        )