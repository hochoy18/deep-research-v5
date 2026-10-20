"""Seam: extract_citations(text, sources) -> list[Citation]

Single entry point for resolving inline `[n]` references against the
aggregated Sources list. Both Research (handoff) and Write (audit) call this.

Behaviour in P1: parse every `[n]` (n ≥ 1) in document order and resolve it
against `sources` by 1-based index. Citations that point past the end of the
list are dropped (so the Report stays self-consistent).
"""

from __future__ import annotations

import re

from .types import Citation, Source


# `[n]` — n is 1+ digits. Surrounding whitespace is allowed. A `[0]` or
# negative number is never valid; both are dropped silently.
_CITATION_RE = re.compile(r"\[(\d+)\]")


def extract_citations(
    text: str,
    sources: list[Source],
) -> list[Citation]:
    """Resolve every `[n]` in `text` against `sources` (1-based, document order).

    Parameters
    ----------
    text:
        Markdown text that may contain inline `[n]` citations.
    sources:
        Aggregated Sources list for the Report. Index `n-1` is the source
        cited by `[n]`.

    Returns
    -------
    list[Citation]
        Citations in document order. Duplicates are preserved (the same `[3]`
        used twice yields two `Citation(n=3)` entries) so the caller can
        audit every reference; if you want uniqueness, deduplicate at the
        caller.

    Notes
    -----
    Out-of-range numbers are dropped, not raised. The seam is intentionally
    tolerant so a typo in one citation doesn't blow up the whole report.
    """
    citations: list[Citation] = []
    for match in _CITATION_RE.finditer(text):
        n = int(match.group(1))
        if n < 1 or n > len(sources):
            continue
        src = sources[n - 1]
        citations.append(
            Citation(
                number=n,
                source_url=src.url,
                source_title=src.title,
            )
        )
    return citations