"""Behavior tests for the search_web seam (P1 stub)."""

from __future__ import annotations

import pytest

from app.seams.search_web import SearchNotConfiguredError, search_web


class TestSearchWeb:
    """The P1 search_web is a stub: it raises until a provider is configured."""

    def test_raises_when_provider_missing(self) -> None:
        with pytest.raises(SearchNotConfiguredError) as exc:
            search_web("rust async runtime")
        assert "rust async runtime" in str(exc.value)
        assert "dashscope" in str(exc.value)

    def test_explicit_provider_in_error(self) -> None:
        with pytest.raises(SearchNotConfiguredError) as exc:
            search_web("x", provider="tavily")
        assert "tavily" in str(exc.value)

    def test_top_k_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            search_web("x", top_k=0)
        with pytest.raises(ValueError):
            search_web("x", top_k=-1)

    def test_unknown_provider_rejected(self) -> None:
        with pytest.raises(ValueError):
            search_web("x", provider="google")  # type: ignore[arg-type]

    def test_default_provider_is_dashscope(self) -> None:
        with pytest.raises(SearchNotConfiguredError) as exc:
            search_web("x")
        assert "dashscope" in str(exc.value)