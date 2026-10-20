"""The Structured Plan schema — the single validation gate for Plans.

The bounds below are the Plan JSON Schema from `CONTEXT.md`, restated as
Pydantic constraints so one definition serves the LLM parser, the DB
writer, and the HTTP layer:

  - Section count      1..8   (0 rejected, >8 tells the user to consolidate)
  - `title`            1..100
  - `brief`            1..500
  - `sub_questions`    0..5 items, each 1..200
  - `note.text`        1..1000

Nothing else may re-declare these numbers. Callers get one of two
outcomes from `parse_plan`: a fully-formed `Plan`, or a
`PlanValidationError` carrying a field-level violation list that the
router turns into the 422 body the user reads.

Per issue #3, `plan_note` is accepted and always NULL in P1 — a
Plan-level Note is a P2 feature.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# --- the bounds, named once ----------------------------------------------

MIN_SECTIONS = 1
MAX_SECTIONS = 8
TITLE_MAX = 100
BRIEF_MAX = 500
MAX_SUB_QUESTIONS = 5
SUB_QUESTION_MAX = 200
NOTE_MAX = 1000

_TOO_MANY_SECTIONS_REASON = (
    f"the plan has more than {MAX_SECTIONS} sections — consolidate them into at "
    f"most {MAX_SECTIONS} before running the research"
)
_TOO_FEW_SECTIONS_REASON = f"a plan needs at least {MIN_SECTIONS} section"


@dataclass(frozen=True)
class Violation:
    """One field-level reason the payload was rejected.

    `field` is a dotted path (`sections[2].sub_questions[1]`) so the UI
    can point at the offending input rather than saying "invalid plan".
    """

    field: str
    message: str


class PlanValidationError(ValueError):
    """Raised when a payload cannot become a Plan.

    `reason` is the single-line summary handed to the user; `violations`
    is the machine-readable detail. Both are safe to serialise — the
    messages are built from schema bounds and model field names, never
    from raw model prose beyond the refusal path (which raises
    `LLMRefusedError` instead).
    """

    def __init__(self, violations: list[Violation]) -> None:
        self.violations = violations
        super().__init__(self.reason)

    @property
    def reason(self) -> str:
        shown = self.violations[:5]
        parts = [f"{v.field}: {v.message}" for v in shown]
        if len(self.violations) > len(shown):
            parts.append(f"(+{len(self.violations) - len(shown)} more)")
        return "; ".join(parts) or "invalid plan"

    def as_payload(self) -> list[dict[str, str]]:
        """JSON-ready violations for the 422 body."""
        return [{"field": v.field, "message": v.message} for v in self.violations]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


SubQuestion = Annotated[str, Field(min_length=1, max_length=SUB_QUESTION_MAX)]


class Note(BaseModel):
    """A free-form Note on a Section (injected into sub-query prompts)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    text: str = Field(min_length=1, max_length=NOTE_MAX)


class Section(BaseModel):
    """One bounded research thread. `id` is assigned by us, never by the model."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    brief: str = Field(min_length=1, max_length=BRIEF_MAX)
    sub_questions: list[SubQuestion] = Field(default_factory=list, max_length=MAX_SUB_QUESTIONS)
    note: Note | None = None

    @field_validator("sub_questions")
    @classmethod
    def _reject_duplicates(cls, value: list[str]) -> list[str]:
        """Reject repeated sub-questions rather than silently dropping them.

        Issue #3 says any out-of-bounds value is rejected. Silently
        rewriting the model's output would hand the user a Plan they never
        got back — they approve what they were shown, so what they were
        shown has to be what the model actually said. Case-insensitive,
        because "When did it start?" twice wastes a search slot just as
        effectively as two identical spellings.
        """
        seen: set[str] = set()
        for item in value:
            key = item.casefold()
            if key in seen:
                raise ValueError(
                    f"duplicate sub-question {item!r}; a Section must not repeat one"
                )
            seen.add(key)
        return value


class PlanPayload(BaseModel):
    """What the model returns, and what a stored Plan round-trips through."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    sections: list[Section] = Field(min_length=MIN_SECTIONS, max_length=MAX_SECTIONS)
    plan_note: str | None = None


class Plan(PlanPayload):
    """A validated Plan revision — the payload plus the bookkeeping a
    `plans` row carries.

    Inheriting keeps `sections` (and its bounds) declared once, and keeps
    `plan_note` honest: it is the same Plan-level Note whether it arrived
    from the model or from a stored row.

    `version` and `approved` mirror the row; issue #3 only ever writes
    version=1 / approved=False. HITL revisions (issue #4) append new rows
    with `version + 1`.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    version: int = Field(default=1, ge=1)
    approved: bool = False
    approved_at: datetime | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    def to_sections_json(self) -> list[dict[str, Any]]:
        """The `plans.sections` column value — section ids included so HITL
        operations (issue #4) can address a Section across revisions."""
        return [section.model_dump(mode="json") for section in self.sections]

    def with_version(self, version: int) -> Plan:
        """A copy at a new revision number. Immutability is the point: every
        HITL edit is a new row, never an in-place rewrite."""
        return self.model_copy(update={"version": version, "updated_at": _utcnow()})


def _format_loc(loc: tuple[Any, ...]) -> str:
    """`('sections', 2, 'sub_questions', 0)` → `sections[2].sub_questions[0]`."""
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out = f"{out}.{part}" if out else str(part)
    return out or "plan"


def _violations_from(exc: ValidationError) -> list[Violation]:
    violations: list[Violation] = []
    for err in exc.errors():
        field = _format_loc(err.get("loc", ()))
        kind = err.get("type", "")
        message = str(err.get("msg", "invalid value"))

        if field == "sections" and kind == "too_long":
            message = _TOO_MANY_SECTIONS_REASON
        elif field == "sections" and kind == "too_short":
            message = _TOO_FEW_SECTIONS_REASON

        if len(message) > 300:
            message = message[:297] + "…"
        violations.append(Violation(field=field, message=message))
    return violations


def parse_sections(raw: Any) -> list[Section]:
    """Validate a bare `sections` array (e.g. a stored `plans.sections` column)."""
    if isinstance(raw, dict):  # tolerate a whole payload arriving here
        raw = raw.get("sections")
    if not isinstance(raw, list):
        raise PlanValidationError(
            [Violation(field="sections", message="expected a list of sections")]
        )
    try:
        return PlanPayload(sections=raw).sections
    except ValidationError as exc:
        raise PlanValidationError(_violations_from(exc)) from exc


def parse_plan(raw: Any) -> Plan:
    """Validate a model payload and return the first Plan revision.

    Accepts the shape the `plan_generate_system` prompt is asked for:
    `{sections: [{title, brief, sub_questions?, note?}], plan_note: null}`.
    Ids, `version`, `approved`, and timestamps are ours to assign.
    """
    if not isinstance(raw, dict):
        raise PlanValidationError(
            [Violation(field="plan", message="expected a JSON object with a 'sections' array")]
        )

    try:
        payload = PlanPayload.model_validate(raw)
    except ValidationError as exc:
        raise PlanValidationError(_violations_from(exc)) from exc

    now = _utcnow()
    return Plan(
        version=1,
        sections=payload.sections,
        plan_note=payload.plan_note,
        approved=False,
        approved_at=None,
        created_at=now,
        updated_at=now,
    )