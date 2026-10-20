"""Seam: call_llm(prompt_id, variables, *, model_override=None) -> str

Single entry point for every LLM call in the project. The seam resolves
`prompt_id` against the prompt registry, fetches prompt text *and* its
config (model, temperature, ...), caches for 60 s, then calls the provider.

**Where a prompt comes from.** Per ADR 0004 the registry is the SSOT for
which model runs which prompt, so resolution asks Langfuse first:

  1. Langfuse prompt API, when `LANGFUSE_*` is configured and answers.
  2. The bundled seed registry (`app/prompts/`) otherwise — or when
     Langfuse is unreachable, because a registry blip must not fail a
     user request when the same prompt is committed to the repo.

**Which model runs it.** Only from prompt config, and only from
Langfuse — the seed registry deliberately carries no `model`, so a real
provider run without a configured registry fails loudly instead of
quietly using a model nobody picked. No model name appears anywhere in
Python or JSON; `tests/test_static/test_model_routing.py` enforces the
Python half by scanning `app/**/*.py`.

**Providers.** `dashscope` (Bailian, OpenAI-compatible HTTP) is the
production path. `stub` is deterministic offline output for dev/demo and
must be opted into with `LLM_PROVIDER=stub` — the default is `dashscope`,
so a deployment without credentials fails closed rather than quietly
serving fake plans.

Production callers MUST NOT pass `model_override`; it exists for debugging
and is checked by code review.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import httpx

from ..config import LLMSettings, get_llm_settings

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
REGISTRY_FILE = PROMPTS_DIR / "registry.json"

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_STUB_PROVIDERS = frozenset({"plan_generate_system"})


class LLMCallError(RuntimeError):
    """Base for every way a seam call can fail to produce a completion.

    Split by who can act on it:

      - `LLMNotConfiguredError` — an operator can fix it (503).
      - `LLMRefusedError` — the user can, by rephrasing (422).
      - plain `LLMCallError` — a caller passed something the prompt could
        not be rendered from. That is our bug, not theirs, so it is
        deliberately *not* caught by the API and surfaces as a 500.
    """


class LLMNotConfiguredError(LLMCallError):
    """Raised when call_llm cannot reach a model: no such prompt, no
    credential, no model in the prompt's config, or a provider outage."""


class LLMRefusedError(LLMCallError):
    """Raised when the upstream LLM refused. User-facing stages (issue #8)
    turn this into HTTP 422 carrying the model's own reason; internal
    stages fall back silently."""


@dataclass(frozen=True)
class ResolvedPrompt:
    """A prompt's text plus the config that says how to run it."""

    prompt_id: str
    text: str
    """The model to run this prompt with. `None` for a seed prompt: per
    ADR 0004 only Langfuse says which model a prompt runs on."""
    model: str | None
    temperature: float | None = None
    max_tokens: int | None = None
    json_mode: bool = False
    optional_variables: tuple[str, ...] = ()
    source: str = "seed"


# --- prompt resolution -----------------------------------------------------

_cache: dict[str, tuple[float, ResolvedPrompt]] = {}
_cache_lock = Lock()


def reset_prompt_cache() -> None:
    """Drop the resolved-prompt cache. Tests call this between cases."""
    with _cache_lock:
        _cache.clear()


def resolve_prompt(prompt_id: str, settings: LLMSettings | None = None) -> ResolvedPrompt:
    """Return the prompt and its config, from cache when warm.

    A cached entry lives for `PROMPT_CACHE_TTL_SECONDS` (60 s by default),
    which is what makes switching a prompt's model a Langfuse-UI action
    rather than a redeploy.
    """
    settings = settings or get_llm_settings()
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(prompt_id)
        if cached and cached[0] > now:
            return cached[1]

    resolved = _resolve_uncached(prompt_id, settings)

    with _cache_lock:
        _cache[prompt_id] = (now + settings.prompt_cache_ttl_seconds, resolved)
    return resolved


def _resolve_uncached(prompt_id: str, settings: LLMSettings) -> ResolvedPrompt:
    if settings.langfuse_configured:
        try:
            return _langfuse_prompt(prompt_id, settings)
        except Exception as exc:  # registry blip: fall back, don't fail the request
            logger.warning("langfuse prompt lookup failed (%s); using bundled seed", exc)
    return _seed_prompt(prompt_id)


def _seed_registry() -> dict[str, dict[str, Any]]:
    try:
        raw = REGISTRY_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        raise LLMNotConfiguredError(f"prompt registry unreadable at {REGISTRY_FILE}: {exc}") from exc
    return json.loads(raw).get("prompts", {})


def _seed_prompt(prompt_id: str) -> ResolvedPrompt:
    entry = _seed_registry().get(prompt_id)
    if entry is None:
        raise LLMNotConfiguredError(
            f"unknown prompt_id {prompt_id!r}; register it in Langfuse or "
            f"{REGISTRY_FILE.name}"
        )

    text_file = PROMPTS_DIR / f"{prompt_id}.md"
    try:
        text = text_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise LLMNotConfiguredError(f"prompt text missing at {text_file}: {exc}") from exc

    return ResolvedPrompt(
        prompt_id=prompt_id,
        text=text,
        # Deliberately absent from the seed registry: ADR 0004 makes
        # Langfuse the only source of truth for which model runs a prompt.
        # A repo-pinned model would be a second SSOT with no audit trail,
        # so a seed prompt simply has no model — `call_llm` then fails
        # visibly rather than quietly serving a model nobody chose.
        model=None,
        temperature=_as_float(entry.get("temperature")),
        max_tokens=_as_int(entry.get("max_tokens")),
        json_mode=bool(entry.get("json_mode", False)),
        optional_variables=tuple(str(v) for v in entry.get("optional_variables", ())),
        source="seed",
    )


def _langfuse_prompt(prompt_id: str, settings: LLMSettings) -> ResolvedPrompt:
    host = str(settings.langfuse_host).rstrip("/")
    token = base64.b64encode(
        f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()
    ).decode()
    response = _http_client(settings).get(
        f"{host}/api/v2/prompts",
        params={"name": prompt_id, "version": "latest"},
        headers={"Authorization": f"Basic {token}"},
        timeout=settings.request_timeout_seconds,
    )
    if response.status_code != 200:
        raise LLMNotConfiguredError(
            f"langfuse prompt lookup returned HTTP {response.status_code} for {prompt_id!r}"
        )

    data = response.json().get("data") or []
    if not data:
        raise LLMNotConfiguredError(f"langfuse has no prompt named {prompt_id!r}")

    entry = data[0]
    config = entry.get("config") or {}
    model = config.get("model")
    if not model:
        raise LLMNotConfiguredError(
            f"langfuse prompt {prompt_id!r} has no model in its config "
            "(ADR 0004: the prompt config is the model-routing SSOT)"
        )

    return ResolvedPrompt(
        prompt_id=prompt_id,
        text=str(entry.get("prompt") or ""),
        model=str(model),
        temperature=_as_float(config.get("temperature")),
        max_tokens=_as_int(config.get("max_tokens")),
        json_mode=bool(config.get("json_mode", False)),
        optional_variables=tuple(str(v) for v in config.get("optional_variables", ())),
        source="langfuse",
    )


def _render(prompt: ResolvedPrompt, variables: dict[str, Any]) -> str:
    """Substitute `{{name}}` placeholders.

    A placeholder with no matching key is an error unless the prompt's
    config lists it under `optional_variables`: silently shipping
    `{{query}}` to the model would produce a confidently wrong plan,
    while `history` is legitimately absent on the first turn. A key
    present but `None` also renders as empty.
    """
    optional = set(prompt.optional_variables)
    missing: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            if name not in optional:
                missing.append(name)
                return match.group(0)
            return ""
        value = variables[name]
        return "" if value is None else str(value)

    rendered = _PLACEHOLDER_RE.sub(substitute, prompt.text)
    if missing:
        raise LLMCallError(
            f"prompt {prompt.prompt_id!r} needs variable(s) {', '.join(sorted(set(missing)))}; "
            f"got {sorted(variables)}"
        )
    return rendered


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _as_int(value: Any) -> int | None:
    return None if value is None else int(value)


# --- providers -------------------------------------------------------------


def _http_client(settings: LLMSettings) -> httpx.Client:
    """The seam's HTTP boundary. Tests substitute this with a mock transport."""
    return httpx.Client(timeout=settings.request_timeout_seconds)


def _dashscope_completion(
    prompt: ResolvedPrompt,
    rendered: str,
    variables: dict[str, Any],
    settings: LLMSettings,
) -> str:
    if not settings.dashscope_api_key:
        raise LLMNotConfiguredError(
            "DASHSCOPE_API_KEY is not set — export it, or set LLM_PROVIDER=stub "
            "to run against the offline stub provider"
        )
    if not prompt.model:
        raise LLMNotConfiguredError(
            f"no model resolved for prompt {prompt.prompt_id!r} (source: "
            f"{prompt.source}). Per ADR 0004 the model comes from Langfuse "
            "prompt config — set LANGFUSE_BASE_URL / LANGFUSE_PUBLIC_KEY / "
            "LANGFUSE_SECRET_KEY, or run with LLM_PROVIDER=stub."
        )

    body: dict[str, Any] = {
        "model": prompt.model,
        "messages": [
            {"role": "system", "content": rendered},
            {"role": "user", "content": json.dumps(variables, ensure_ascii=False)},
        ],
    }
    if prompt.temperature is not None:
        body["temperature"] = prompt.temperature
    if prompt.max_tokens is not None:
        body["max_tokens"] = prompt.max_tokens
    if prompt.json_mode:
        body["response_format"] = {"type": "json_object"}

    url = f"{settings.dashscope_base_url.rstrip('/')}/chat/completions"
    try:
        response = _http_client(settings).post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {settings.dashscope_api_key}"},
        )
    except httpx.HTTPError as exc:
        raise LLMNotConfiguredError(f"llm provider unreachable: {exc}") from exc

    if response.status_code != 200:
        raise LLMNotConfiguredError(
            f"llm provider returned HTTP {response.status_code} for prompt "
            f"{prompt.prompt_id!r}: {response.text[:200]}"
        )

    return _completion_text(prompt.prompt_id, response.json())


def _completion_text(prompt_id: str, payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise LLMNotConfiguredError(f"llm provider returned no choices for {prompt_id!r}")

    choice = choices[0]
    finish_reason = str(choice.get("finish_reason") or "")
    content = (choice.get("message") or {}).get("content") or ""

    if finish_reason == "content_filter":
        raise LLMRefusedError(
            f"the model declined this request (finish_reason=content_filter) for {prompt_id!r}"
        )
    if not content.strip():
        raise LLMRefusedError(
            f"the model returned an empty completion for {prompt_id!r} "
            f"(finish_reason={finish_reason or 'unknown'})"
        )
    return str(content)


# --- the stub provider -----------------------------------------------------

# Three angles that apply to any researchable question. The stub exists so
# the Plan → render path is runnable without credentials; it is not a
# substitute for a model and never claims to be one.
_STUB_ANGLES: tuple[tuple[str, str], ...] = (
    ("Background & context", "Establish where {topic} came from and what shaped it."),
    ("Where it stands today", "Survey the current state of {topic}, including the main competing views."),
    ("Open questions", "Identify what is still unsettled about {topic} and what evidence would settle it."),
)


def _stub_completion(prompt_id: str, variables: dict[str, Any]) -> str:
    if prompt_id not in _STUB_PROVIDERS:
        raise LLMNotConfiguredError(
            f"LLM_PROVIDER=stub has no generator for {prompt_id!r}; "
            "use a real provider for this stage"
        )

    query = str(variables.get("query") or "").strip()
    if not query:
        raise LLMNotConfiguredError("prompt 'plan_generate_system' needs a non-empty query")

    topic = query if len(query) <= 200 else query[:197] + "…"
    sections = [
        {
            "title": title,
            "brief": brief.format(topic=topic)[:500],
            "sub_questions": [f"What is the state of the evidence on: {topic}?"[:200]],
            "note": None,
        }
        for title, brief in _STUB_ANGLES
    ]
    logger.warning(
        "LLM_PROVIDER=stub — returning a deterministic placeholder plan, "
        "not model output (prompt_id=%s)",
        prompt_id,
    )
    return json.dumps({"sections": sections, "plan_note": None}, ensure_ascii=False)


# --- the seam --------------------------------------------------------------


def call_llm(
    prompt_id: str,
    variables: dict[str, Any],
    *,
    model_override: str | None = None,
) -> str:
    """Resolve `prompt_id` against the prompt registry and call the LLM.

    Returns the raw completion text. Refusal / parse failures are signalled
    via `LLMRefusedError` so callers in user-facing stages can return
    HTTP 422.

    Parameters
    ----------
    prompt_id:
        Stable identifier registered in the Langfuse prompt registry
        (or in the bundled seed registry).
    variables:
        Template variables for the prompt; every `{{placeholder}}` in the
        prompt must have a matching key. `None` renders as empty.
    model_override:
        Debug-only override of the model column. Production callers pass
        `None` (the default); code review rejects any non-None value at a
        non-test call site.

    Raises
    ------
    LLMNotConfiguredError
        Unknown prompt, missing model config, missing credentials, or an
        unreachable registry/provider. An operator fixes these — the API
        answers 503.
    LLMRefusedError
        Upstream refusal; caller decides 422 vs silent fallback.
    LLMCallError
        The prompt needed a variable the caller did not pass. A bug on
        our side, so it is left uncaught and surfaces as a 500.
    """
    settings = get_llm_settings()
    prompt = resolve_prompt(prompt_id, settings)
    rendered = _render(prompt, variables)

    if settings.provider == "stub":
        return _stub_completion(prompt_id, variables)

    if settings.provider != "dashscope":
        raise LLMNotConfiguredError(
            f"unknown LLM_PROVIDER {settings.provider!r}; expected 'dashscope' or 'stub'"
        )

    if model_override:
        # Debug path: the model column stays configuration everywhere else.
        prompt = ResolvedPrompt(
            prompt_id=prompt.prompt_id,
            text=prompt.text,
            model=model_override,
            temperature=prompt.temperature,
            max_tokens=prompt.max_tokens,
            json_mode=prompt.json_mode,
            source=prompt.source,
        )

    return _dashscope_completion(prompt, rendered, variables, settings)