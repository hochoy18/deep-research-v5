"""Pydantic request/response schemas for the `/sessions*` endpoints.

The Plan shape is *not* redefined here — it is imported from
`app.plan.schemas`, which owns the bounds. These models are the HTTP
envelope only.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from ..plan.schemas import Plan

# Long enough for a real research question, short enough that a pasted
# document fails fast instead of becoming a 20k-token prompt.
MAX_QUERY_CHARS = 2000


class CreateSessionRequest(BaseModel):
    query: str = Field(..., max_length=MAX_QUERY_CHARS)

    @field_validator("query")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("query must not be empty")
        return cleaned


class CreateSessionResponse(BaseModel):
    session_id: uuid.UUID


class SessionOut(BaseModel):
    """A Session as the browser sees it.

    Named for the runtime concept, not the row it persists to:
    CONTEXT.md defines "Session" as the user- **and frontend-facing**
    term, with "Conversation" reserved for `app_db.conversations`. The
    inner field is `session_id` for the same reason — the API never says
    `conversation_id` to a client.
    """

    session_id: uuid.UUID
    query: str
    created_at: datetime
    updated_at: datetime


class PlanOut(BaseModel):
    """The Plan as the frontend renders it.

    `approved` and `version` travel with it because the Plan page shows
    the current revision and must grey out its controls once approved
    (issue #4).
    """

    plan_id: uuid.UUID
    version: int
    approved: bool
    approved_at: datetime | None
    sections: list[dict[str, Any]]
    plan_note: str | None = None

    @classmethod
    def from_domain(cls, plan: Plan, *, plan_id: uuid.UUID | None = None) -> PlanOut:
        return cls(
            plan_id=plan_id or plan.id,
            version=plan.version,
            approved=plan.approved,
            approved_at=plan.approved_at,
            sections=plan.to_sections_json(),
            plan_note=plan.plan_note,
        )


class SessionStateResponse(BaseModel):
    """`GET /sessions/{id}/state` — enough for a refreshing browser to
    render the page without waiting for the next event."""

    session: SessionOut
    plan: PlanOut | None = None
    report_md: str | None = None
    latest_event_id: int = 0