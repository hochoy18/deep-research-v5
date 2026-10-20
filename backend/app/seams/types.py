"""Shared dataclasses for the seam layer.

These are the value objects that flow across the seam boundary. They are
intentionally plain dataclasses so the seams remain trivially testable
without any LLM-side imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Source:
    """One web search result, deduplicated by URL across a Session."""

    url: str
    title: str
    snippet: str
    content: str | None = None


@dataclass(frozen=True)
class Citation:
    """An inline `[n]` reference resolved against a Sources list."""

    number: int
    source_url: str
    source_title: str


@dataclass
class EvalResult:
    """Return value of `evaluate(rubric_name, text, context=None)`."""

    passed: bool
    reason: str
    score: float | None = None
    # Free-form rubric-specific extras; kept loose on purpose.
    extras: dict[str, Any] = field(default_factory=dict)