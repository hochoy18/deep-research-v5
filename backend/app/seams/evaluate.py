"""Seam: evaluate(rubric_name, text, *, context=None) -> EvalResult

Single entry point for evaluation. Research and Write both call this seam.
P1 ships this as a stub: with no rubric registry configured the seam returns
a deterministic pass so the rest of the system has *something* to work
against; later tickets replace it with the real rubric-driven evaluator.

Why pass-by-default in P1: the spec scopes "no eval scoring" to P1 — so the
stub exists to keep callers compiling and to give tests a predictable value.
"""

from __future__ import annotations

from typing import Any

from .types import EvalResult


def evaluate(
    rubric_name: str,
    text: str,
    *,
    context: dict[str, Any] | None = None,
) -> EvalResult:
    """Score `text` against `rubric_name`, optionally with `context`.

    Parameters
    ----------
    rubric_name:
        Stable rubric identifier registered in the Langfuse prompt registry.
    text:
        The text under evaluation.
    context:
        Optional auxiliary inputs (e.g. sources, plan, section_brief).

    Returns
    -------
    EvalResult
        `passed=True`, `reason='p1-stub'`, `score=None` when no rubric is
        registered. Real rubrics return richer results in later tickets.
    """
    if not rubric_name:
        raise ValueError("rubric_name must be a non-empty string")

    return EvalResult(
        passed=True,
        reason="p1-stub",
        score=None,
        extras={"rubric": rubric_name, "context_keys": sorted((context or {}).keys())},
    )