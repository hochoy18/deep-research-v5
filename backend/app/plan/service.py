"""Plan layer service — one Session's Plan, from Query to stored revision.

This is the only place in the Plan layer that knows how a Plan is made:

  1. `call_llm('plan_generate_system', ...)` — through the seam, never a
     provider SDK (ADR 0003).
  2. the completion is turned into a `Plan` and validated against the
     Plan JSON Schema (`app/plan/schemas.py`).
  3. the first revision is written as a `plans` row at version=1,
     approved=false, plan_note=NULL.

Two ways a completion fails, and they mean different things to the user:

  - the model declined (`{"refusal": "..."}`) or answered in prose →
    `PlanRefusedError`. The model's own words become the 422 reason.
  - the model answered in the right shape but out of bounds (nine
    sections, a 300-character title) → `PlanValidationError`. The
    violation list becomes the 422 body.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Conversation, Message, PlanRow
from ..seams.call_llm import LLMRefusedError, call_llm
from .schemas import Plan, PlanValidationError, parse_plan, parse_sections

PLAN_PROMPT_ID = "plan_generate_system"

# How much of a prose answer to quote back as the refusal reason. Long
# enough for the model to be useful, short enough for a 422 body.
MAX_REASON_CHARS = 500


class PlanRefusedError(RuntimeError):
    """The model declined to plan this Query.

    `reason` is the model's own words and is shown to the user verbatim,
    so the UI can invite a rephrase.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class PlanService:
    """Stateless service: pass a Session, get back dataclasses and models."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # --- generation --------------------------------------------------------

    def generate(self, query: str) -> Plan:
        """Run `plan_generate` and return a validated Plan.

        Raises `PlanRefusedError` when the model declines, and
        `PlanValidationError` when the completion cannot become a Plan.
        """
        try:
            completion = call_llm(PLAN_PROMPT_ID, {"query": query, "history": None})
        except LLMRefusedError as exc:
            # The seam saw an empty or content-filtered completion; the
            # stage is user-facing, so the reason travels to the client.
            raise PlanRefusedError(str(exc)) from exc

        return self.parse_completion(completion)

    def parse_completion(self, completion: str) -> Plan:
        """Turn a raw completion into a validated Plan.

        Unparseable prose is treated as a refusal: a model that answers in
        sentences has not answered the question it was asked, and showing
        the user its words is more useful than a schema complaint.
        """
        try:
            payload: Any = json.loads(completion)
        except (json.JSONDecodeError, TypeError):
            raise PlanRefusedError(_clip(completion, MAX_REASON_CHARS, "the model did not answer in JSON"))

        if isinstance(payload, dict):
            refusal = payload.get("refusal")
            if isinstance(refusal, str) and refusal.strip():
                raise PlanRefusedError(_clip(refusal.strip(), MAX_REASON_CHARS))

        return parse_plan(payload)

    # --- persistence -------------------------------------------------------

    def open_conversation(self, conversation_id: uuid.UUID, user_id: uuid.UUID, query: str) -> Conversation:
        """Create the Conversation and the user's first Message.

        Called inside the same transaction as `generate()` and
        `persist_first_revision()`, so a refused query leaves no rows
        behind: no Session, no transcript entry, no Plan.
        """
        conversation = Conversation(id=conversation_id, user_id=user_id, query=query)
        self._session.add(conversation)
        self._session.add(
            Message(
                id=uuid.uuid4(),
                conversation_id=conversation_id,
                role="user",
                content=query,
            )
        )
        self._session.flush()
        return conversation

    def persist_first_revision(self, conversation_id: uuid.UUID, plan: Plan) -> PlanRow:
        """Write the version=1 Plan row.

        Later revisions are appended by the HITL operations (issue #4) —
        `version + 1` per edit, never an in-place rewrite.
        """
        row = PlanRow(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            sections=plan.to_sections_json(),
            plan_note=None,  # Plan-level Note is P2
            version=plan.version,
            approved=False,
            approved_at=None,
        )
        self._session.add(row)
        self._session.flush()
        return row

    # --- reads -------------------------------------------------------------

    def latest_plan(self, conversation_id: uuid.UUID) -> PlanRow | None:
        """The newest revision — the `version DESC` read the index exists for."""
        return self._session.execute(
            select(PlanRow)
            .where(PlanRow.conversation_id == conversation_id)
            .order_by(PlanRow.version.desc())
            .limit(1)
        ).scalar_one_or_none()

    def conversation_for(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> Conversation | None:
        """The Conversation, but only if `user_id` owns it.

        A Conversation belonging to someone else reads as absent rather
        than forbidden: the response body must not confirm that another
        user's session id exists.
        """
        return self._session.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        ).scalar_one_or_none()

    def plan_to_domain(self, row: PlanRow) -> Plan:
        """Rebuild the validated `Plan` from a stored row."""
        return Plan(
            id=row.id,
            version=row.version,
            sections=parse_sections(row.sections),
            plan_note=row.plan_note,
            approved=row.approved,
            approved_at=row.approved_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


def _clip(text: str, limit: int, prefix: str = "") -> str:
    text = (text or "").strip()
    if not text:
        return prefix or "the model returned nothing usable"
    if len(text) <= limit:
        return f"{prefix}{text}" if prefix else text
    return f"{prefix}{text[: limit - 1]}…"