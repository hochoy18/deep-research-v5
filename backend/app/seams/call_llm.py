"""Seam: call_llm(prompt_id, variables, *, model_override=None) -> str

Single entry point for every LLM call in the project. The seam resolves
`prompt_id` against the Langfuse registry, fetches prompt text *and* its
config (model, temperature, ...), caches for 60 s, then calls the provider.

P1 ships this as a stub: the prompt registry is empty, so the seam raises
`LLMNotConfiguredError`. Downstream layers (Plan / Research / Write) come in
later tickets; tests substitute this seam directly. Per ADR 0004, the model
column is configuration in Langfuse, never code.

Production callers MUST NOT pass `model_override`; it exists for debugging
and is checked by code review.
"""

from __future__ import annotations

from typing import Any


class LLMNotConfiguredError(RuntimeError):
    """Raised when call_llm is invoked before a Langfuse prompt registry exists."""


class LLMRefusedError(RuntimeError):
    """Raised when the upstream LLM refused (used by user-facing stages)."""


def call_llm(
    prompt_id: str,
    variables: dict[str, Any],
    *,
    model_override: str | None = None,
) -> str:
    """Resolve `prompt_id` against the Langfuse registry and call the LLM.

    Returns the raw completion text. Refusal / parse failures are signalled via
    `LLMRefusedError` so callers in user-facing stages can return HTTP 422.

    Parameters
    ----------
    prompt_id:
        Stable identifier registered in the Langfuse prompt registry.
    variables:
        Template variables for the prompt; keys must match the prompt's
        declared input set.
    model_override:
        Debug-only override of the model column. Production callers pass
        `None` (the default); code review rejects any non-None value at a
        non-test call site.

    Raises
    ------
    LLMNotConfiguredError
        In P1 the Langfuse prompt registry is not yet wired, so every call
        raises. Later tickets replace the body with the real implementation.
    LLMRefusedError
        Upstream refusal; caller decides 422 vs silent fallback.
    """
    # P1 stub: registry wiring lives in a later ticket. Behaviour is a single
    # typed error so callers don't accidentally treat "model not configured"
    # as "empty completion".
    raise LLMNotConfiguredError(
        f"call_llm({prompt_id!r}) not configured yet; "
        "Langfuse prompt registry lands in a later ticket."
    )