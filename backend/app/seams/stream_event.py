"""Seam: stream_event(event_type, payload) -> None

Single entry point for sending events to the frontend. P1 ships this as a
stub: events are appended to an in-memory ring buffer so tests can assert on
them, and a no-op push to any live SSE subscriber.

Real implementation (later ticket) writes to:
  1. `app_db.messages` so the stream is replayable by `Last-Event-ID`.
  2. Any live SSE subscriber for `GET /sessions/{id}/events`.
"""

from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Any

# P1 stub storage. The Session-scoped buffer is keyed by session_id so tests
# can assert on events without cross-talk. The capacity is generous; later
# tickets replace this with real persistence + SSE fan-out.
_buffers: dict[str, deque[dict[str, Any]]] = {}
_event_counter = 0
_lock = Lock()


class StreamEventError(RuntimeError):
    """Raised when stream_event cannot accept an event."""


def stream_event(event_type: str, payload: dict[str, Any]) -> None:
    """Record an event for SSE delivery.

    Parameters
    ----------
    event_type:
        One of `plan_ready`, `research_progress`, `report_ready`, `error`.
        Other values are accepted (logging will surface them) but are not in
        the P1 contract.
    payload:
        Event body. For `research_progress` the payload includes
        `{section_index, total_sections, sources_count}` per spec.

    Notes
    -----
    The P1 stub does not raise — callers in Plan / Research / Write can rely
    on this being non-blocking. The single error path is `payload` not being
    a dict, so caller mistakes are loud.
    """
    if not isinstance(payload, dict):
        raise StreamEventError(f"payload must be a dict, got {type(payload).__name__}")

    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        # The seam is permissive: missing session_id is allowed in P1 (the
        # backend tests that don't go through the SSE router may omit it),
        # but it logs a synthetic key so events don't bleed across sessions
        # in tests.
        session_id = "_unscoped"

    global _event_counter
    with _lock:
        _event_counter += 1
        event_id = _event_counter
        buf = _buffers.setdefault(session_id, deque(maxlen=10_000))
        buf.append({"id": event_id, "event": event_type, "data": payload})


def get_buffer(session_id: str) -> list[dict[str, Any]]:
    """Test helper: return the recorded events for a session in order."""
    with _lock:
        return list(_buffers.get(session_id, []))


def reset_buffer(session_id: str | None = None) -> None:
    """Test helper: clear recorded events."""
    global _event_counter
    with _lock:
        if session_id is None:
            _buffers.clear()
            _event_counter = 0
        else:
            _buffers.pop(session_id, None)