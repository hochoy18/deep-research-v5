"""Behaviour tests for the Structured Plan schema.

Pure validation — no DB, no LLM, no graph. The bounds are fixed by the
Plan JSON Schema in `CONTEXT.md` and the P1 acceptance list in
`docs/milestones.md`:

  - Section count      1..8   (0 rejected, >8 prompts consolidation)
  - title              1..100
  - brief              1..500
  - sub_questions      0..5 items, each 1..200
  - note.text          1..1000

The public interface is `parse_plan(raw)` — it takes the shape the model
returns and either yields a `Plan` or raises `PlanValidationError` with a
field-level violation list. Every other layer consumes the same function,
so a bound enforced here is enforced everywhere.
"""

from __future__ import annotations

import uuid

import pytest

from app.plan.schemas import PlanValidationError, parse_plan


def _section(**overrides: object) -> dict:
    base: dict = {
        "title": "Background",
        "brief": "Establish the historical context of the topic.",
        "sub_questions": ["When did it start?", "Who were the early actors?"],
    }
    base.update(overrides)
    return base


def _raw(*sections: dict) -> dict:
    return {"sections": list(sections), "plan_note": None}


def _fields(exc: PlanValidationError) -> set[str]:
    return {v.field for v in exc.violations}


class TestHappyPath:
    def test_parses_three_sections_in_order(self) -> None:
        raw = _raw(_section(title="A"), _section(title="B"), _section(title="C"))
        plan = parse_plan(raw)

        assert [s.title for s in plan.sections] == ["A", "B", "C"]
        assert all(uuid.UUID(str(s.id)) for s in plan.sections)

    def test_first_revision_is_version_one_and_unapproved(self) -> None:
        plan = parse_plan(_raw(_section()))
        assert plan.version == 1
        assert plan.approved is False
        assert plan.approved_at is None

    def test_absent_optional_fields_get_empty_defaults(self) -> None:
        raw = {"sections": [{"title": "A", "brief": "b"}]}
        plan = parse_plan(raw)

        assert plan.sections[0].sub_questions == []
        assert plan.sections[0].note is None

    def test_eight_sections_is_the_upper_bound_not_a_violation(self) -> None:
        raw = _raw(*[_section(title=f"S{i}") for i in range(8)])
        assert len(parse_plan(raw).sections) == 8


class TestSectionCount:
    def test_zero_sections_rejected(self) -> None:
        with pytest.raises(PlanValidationError) as exc:
            parse_plan(_raw())
        assert "sections" in _fields(exc.value)

    def test_more_than_eight_sections_rejected_with_consolidation_hint(self) -> None:
        raw = _raw(*[_section(title=f"S{i}") for i in range(9)])
        with pytest.raises(PlanValidationError) as exc:
            parse_plan(raw)

        assert "sections" in _fields(exc.value)
        # The user is told what to do about it, not just that it failed.
        assert "consolidat" in exc.value.reason.lower()

    def test_missing_sections_key_rejected(self) -> None:
        with pytest.raises(PlanValidationError):
            parse_plan({"plan_note": None})


class TestFieldBounds:
    def test_title_upper_bound(self) -> None:
        assert len(parse_plan(_raw(_section(title="t" * 100))).sections[0].title) == 100
        with pytest.raises(PlanValidationError) as exc:
            parse_plan(_raw(_section(title="t" * 101)))
        assert "sections[0].title" in _fields(exc.value)

    def test_title_empty_rejected(self) -> None:
        with pytest.raises(PlanValidationError) as exc:
            parse_plan(_raw(_section(title="")))
        assert "sections[0].title" in _fields(exc.value)

    def test_brief_upper_bound(self) -> None:
        raw = _raw(_section(brief="b" * 500))
        assert len(parse_plan(raw).sections[0].brief) == 500
        with pytest.raises(PlanValidationError) as exc:
            parse_plan(_raw(_section(brief="b" * 501)))
        assert "sections[0].brief" in _fields(exc.value)

    def test_brief_empty_rejected(self) -> None:
        with pytest.raises(PlanValidationError) as exc:
            parse_plan(_raw(_section(brief="   ")))
        assert "sections[0].brief" in _fields(exc.value)

    def test_at_most_five_sub_questions(self) -> None:
        raw = _raw(_section(sub_questions=[f"q{i}" for i in range(5)]))
        assert len(parse_plan(raw).sections[0].sub_questions) == 5

        with pytest.raises(PlanValidationError) as exc:
            parse_plan(_raw(_section(sub_questions=[f"q{i}" for i in range(6)])))
        assert "sections[0].sub_questions" in _fields(exc.value)

    def test_sub_question_upper_bound_is_200(self) -> None:
        raw = _raw(_section(sub_questions=["q" * 200]))
        assert len(parse_plan(raw).sections[0].sub_questions[0]) == 200

        with pytest.raises(PlanValidationError) as exc:
            parse_plan(_raw(_section(sub_questions=["q" * 201])))
        assert "sections[0].sub_questions[0]" in _fields(exc.value)

    def test_sub_question_empty_string_rejected(self) -> None:
        with pytest.raises(PlanValidationError) as exc:
            parse_plan(_raw(_section(sub_questions=["ok", "  "])))
        assert "sections[0].sub_questions[1]" in _fields(exc.value)

    def test_note_text_upper_bound_is_1000(self) -> None:
        raw = _raw(_section(note={"text": "n" * 1000}))
        note = parse_plan(raw).sections[0].note
        assert note is not None and len(note.text) == 1000

        with pytest.raises(PlanValidationError) as exc:
            parse_plan(_raw(_section(note={"text": "n" * 1001})))
        assert "sections[0].note.text" in _fields(exc.value)

    def test_note_text_empty_rejected(self) -> None:
        with pytest.raises(PlanValidationError) as exc:
            parse_plan(_raw(_section(note={"text": ""})))
        assert "sections[0].note.text" in _fields(exc.value)


class TestViolationReporting:
    def test_every_out_of_bounds_field_is_reported_at_once(self) -> None:
        raw = _raw(
            _section(title="", brief="", sub_questions=["q" * 201]),
            _section(title="ok", brief="ok"),
            _section(title="t" * 101, brief="b" * 501),
        )
        with pytest.raises(PlanValidationError) as exc:
            parse_plan(raw)

        assert {
            "sections[0].title",
            "sections[0].brief",
            "sections[0].sub_questions[0]",
            "sections[2].title",
            "sections[2].brief",
        }.issubset(_fields(exc.value))

    def test_reason_is_a_single_human_readable_summary(self) -> None:
        with pytest.raises(PlanValidationError) as exc:
            parse_plan(_raw(_section(title="t" * 101)))
        # Used verbatim as the 422 body the frontend shows the user.
        assert "title" in exc.value.reason

    def test_non_dict_payload_rejected(self) -> None:
        with pytest.raises(PlanValidationError):
            parse_plan(["not", "a", "dict"])  # type: ignore[arg-type]


class TestDuplicateSubQuestions:
    """The spec says any out-of-bounds value is rejected, and silently
    rewriting the model's output is a form of lying: the user reviews a
    Plan they did not get back. So a repeated sub-question is a violation,
    not something to quietly drop."""

    def test_a_repeated_sub_question_is_rejected(self) -> None:
        raw = _raw(_section(sub_questions=["When did it start?", "when did it start?"]))

        with pytest.raises(PlanValidationError) as exc:
            parse_plan(raw)

        assert "sections[0].sub_questions" in _fields(exc.value)

    def test_the_reason_names_the_duplication(self) -> None:
        raw = _raw(_section(sub_questions=["Same?", "Same?"]))

        with pytest.raises(PlanValidationError) as exc:
            parse_plan(raw)

        assert "duplicate" in exc.value.reason.lower()

    def test_distinct_sub_questions_still_pass(self) -> None:
        raw = _raw(_section(sub_questions=["a question", "another question"]))

        assert parse_plan(raw).sections[0].sub_questions == ["a question", "another question"]