"""Behavior tests for the evaluate seam (P1 stub)."""

from __future__ import annotations

import pytest

from app.seams.evaluate import evaluate
from app.seams.types import EvalResult


class TestEvaluate:
    """The P1 evaluate is a stub: it passes by default, with deterministic shape."""

    def test_returns_passed_by_default(self) -> None:
        result = evaluate("research_eval_per_sub_query", "some text")
        assert isinstance(result, EvalResult)
        assert result.passed is True
        assert result.reason == "p1-stub"
        assert result.score is None

    def test_rubric_name_recorded_in_extras(self) -> None:
        result = evaluate("write_judge_quality", "final draft")
        assert result.extras["rubric"] == "write_judge_quality"

    def test_context_keys_are_recorded_when_provided(self) -> None:
        result = evaluate(
            "research_eval_per_sub_query",
            "text",
            context={"section_brief": "X", "sources": []},
        )
        assert result.extras["context_keys"] == ["section_brief", "sources"]

    def test_context_none_yields_empty_keys(self) -> None:
        result = evaluate("r", "t")
        assert result.extras["context_keys"] == []

    def test_empty_rubric_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            evaluate("", "text")