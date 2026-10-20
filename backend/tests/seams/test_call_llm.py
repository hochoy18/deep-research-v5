"""Behavior tests for the call_llm seam (P1 stub)."""

from __future__ import annotations

import pytest

from app.seams.call_llm import LLMNotConfiguredError, call_llm


class TestCallLlm:
    """The P1 call_llm is a stub: it raises until the registry lands."""

    def test_raises_when_registry_missing(self) -> None:
        with pytest.raises(LLMNotConfiguredError) as exc:
            call_llm("plan_generate_system", {"query": "what is X?"})
        assert "plan_generate_system" in str(exc.value)

    def test_variables_are_ignored_in_p1(self) -> None:
        """The stub does not introspect `variables`; the registry will."""
        with pytest.raises(LLMNotConfiguredError):
            call_llm(
                "research_sub_query_generate_system",
                {"section_title": "X", "section_brief": "Y", "note": None},
            )

    def test_model_override_does_not_affect_p1_stub(self) -> None:
        """model_override is part of the contract even though the body ignores it."""
        with pytest.raises(LLMNotConfiguredError):
            call_llm(
                "write_outline_system",
                {"plan": {}, "sources": []},
                model_override="qwen-max",
            )

    def test_signature_accepts_only_kwargs_for_model_override(self) -> None:
        """The contract locks `model_override` to keyword-only."""
        with pytest.raises(TypeError):
            # mypy/ruff both flag this; the runtime confirms it.
            call_llm("plan_generate_system", {"query": "x"}, "qwen-max")  # type: ignore[misc]