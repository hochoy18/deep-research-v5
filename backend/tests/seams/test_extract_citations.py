"""Behavior tests for the extract_citations seam."""

from __future__ import annotations

from app.seams.extract_citations import extract_citations
from app.seams.types import Source


def _sources(n: int) -> list[Source]:
    return [
        Source(url=f"https://example.com/{i}", title=f"src-{i}", snippet=f"s{i}")
        for i in range(1, n + 1)
    ]


class TestExtractCitations:
    def test_resolves_inline_citations_in_order(self) -> None:
        text = "Some claim [1] followed by [2] then back to [1]."
        sources = _sources(2)
        cits = extract_citations(text, sources)
        assert [c.number for c in cits] == [1, 2, 1]
        assert cits[0].source_url == "https://example.com/1"
        assert cits[1].source_url == "https://example.com/2"

    def test_out_of_range_citations_dropped(self) -> None:
        text = "ok [1], bad [5], ok [2]"
        sources = _sources(2)
        cits = extract_citations(text, sources)
        assert [c.number for c in cits] == [1, 2]

    def test_zero_and_negative_dropped(self) -> None:
        text = "[0] then [-3] then [1]"
        sources = _sources(1)
        cits = extract_citations(text, sources)
        assert [c.number for c in cits] == [1]

    def test_empty_text_returns_empty_list(self) -> None:
        assert extract_citations("", _sources(5)) == []

    def test_no_citations_returns_empty_list(self) -> None:
        text = "no citations here, only [abc] garbage"
        assert extract_citations(text, _sources(5)) == []

    def test_multi_digit_numbers(self) -> None:
        text = "[10] and [11]"
        sources = _sources(11)
        cits = extract_citations(text, sources)
        assert [c.number for c in cits] == [10, 11]