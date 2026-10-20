"""Seam: search_web(query, top_k=4, *, provider='dashscope') -> list[Source]

Single entry point for web search. The named `provider` is called first; on
failure the seam falls back to Tavily. P1 ships this as a stub: with no
provider configured the seam raises `SearchNotConfiguredError`.

Each result is normalised to `Source { url, title, snippet, content? }` so
callers never see provider-specific shapes. Per Session, identical URLs are
deduplicated downstream (in the Research layer's `merge_sources`), not here.
"""

from __future__ import annotations

from .types import Source


class SearchNotConfiguredError(RuntimeError):
    """Raised when search_web is invoked before a provider is configured."""


def search_web(
    query: str,
    top_k: int = 4,
    *,
    provider: str = "dashscope",
) -> list[Source]:
    """Search the web and return normalised Source objects.

    Parameters
    ----------
    query:
        Natural-language search query.
    top_k:
        Maximum number of results to return (1 ≤ top_k ≤ 10).
    provider:
        Primary provider name. Supported values are `'dashscope'` (Bailian)
        and `'tavily'`. The seam picks the fallback automatically; callers
        do not name it.

    Raises
    ------
    SearchNotConfiguredError
        In P1 no provider credentials are wired. Later tickets replace the
        body with the real implementation.
    """
    if top_k < 1:
        raise ValueError(f"top_k must be ≥ 1, got {top_k}")
    if provider not in {"dashscope", "tavily"}:
        raise ValueError(f"unknown provider {provider!r}")

    raise SearchNotConfiguredError(
        f"search_web({query!r}, provider={provider!r}) not configured yet; "
        "primary + Tavily fallback land in a later ticket."
    )