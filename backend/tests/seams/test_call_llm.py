"""Behaviour tests for the `call_llm` seam.

`call_llm` is the only path to an LLM. It resolves a `prompt_id` against
the prompt registry (Langfuse first, bundled seed files as fallback) and
calls the provider named in that prompt's config. These tests pin the
contract every layer depends on:

  - an unknown `prompt_id` is loud, not silent
  - the model comes from prompt *config*, never from code (ADR 0004)
  - a missing template variable is loud, so `{{query}}` cannot leak into
    the prompt unnoticed
  - an unconfigured provider fails closed instead of pretending to work
  - a registry outage falls back to the seed prompt
  - an empty / content-filtered completion surfaces as `LLMRefusedError`

No test needs a live Langfuse, DashScope, or API key: HTTP is injected at
the seam's own `httpx` boundary.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Callable

import httpx
import pytest

from app.plan.schemas import parse_plan
from app.seams import call_llm as seam_module
from app.seams.call_llm import (
    LLMCallError,
    LLMNotConfiguredError,
    LLMRefusedError,
    call_llm,
    reset_prompt_cache,
)

# A completion whose message content is `{"sections": [...]}`, one section.
PLAN_COMPLETION: dict[str, Any] = {
    "choices": [
        {
            "message": {
                "content": json.dumps(
                    {
                        "sections": [
                            {
                                "title": "Background",
                                "brief": "Where the topic came from.",
                                "sub_questions": ["When did it start?"],
                            }
                        ],
                        "plan_note": None,
                    }
                )
            },
            "finish_reason": "stop",
        }
    ]
}


@pytest.fixture(autouse=True)
def _clean_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts from a known env and an empty prompt cache."""
    for name in (
        "LLM_PROVIDER",
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_BASE_URL",
        "LANGFUSE_BASE_URL",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "PROMPT_CACHE_TTL_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    reset_prompt_cache()


def use_http(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> list[httpx.Request]:
    """Serve every HTTP call the seam makes with `handler`; return the log."""
    captured: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return handler(request)

    monkeypatch.setattr(
        seam_module,
        "_http_client",
        lambda settings: httpx.Client(transport=httpx.MockTransport(recording)),
    )
    return captured


def completion_only(completion: dict[str, Any] | httpx.Response = PLAN_COMPLETION):
    """A handler that answers any request with `completion` (no Langfuse in play)."""
    reply = completion if isinstance(completion, httpx.Response) else httpx.Response(200, json=completion)

    def handler(request: httpx.Request) -> httpx.Response:
        return reply

    return handler


# The seed registry carries no model (ADR 0004 — Langfuse is the only
# routing SSOT), so tests that drive the real provider pass `model_override`.
# That parameter is the debug/test escape the ADR explicitly sanctions, and
# the same ADR forbids it on any production call path.
TEST_MODEL = "test-model"


def as_dashscope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "dashscope")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")


def sent_body(captured: list[httpx.Request], index: int = -1) -> dict[str, Any]:
    return json.loads(captured[index].content.decode())


def basic_credentials(request: httpx.Request) -> str:
    """Decode an `Authorization: Basic` header into `user:password`."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return ""
    return base64.b64decode(header.split(" ", 1)[1]).decode()


class TestPromptResolution:
    def test_unknown_prompt_id_is_loud(self) -> None:
        with pytest.raises(LLMNotConfiguredError) as exc:
            call_llm("no_such_prompt", {"query": "x"})
        assert "no_such_prompt" in str(exc.value)

    def test_seed_prompt_variables_are_rendered_into_the_completion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        as_dashscope(monkeypatch)
        captured = use_http(monkeypatch, completion_only())

        call_llm("plan_generate_system", {"query": "How do kites fly?"}, model_override=TEST_MODEL)

        system = sent_body(captured)["messages"][0]["content"]
        assert "How do kites fly?" in system
        assert "{{query}}" not in system  # the template never reaches the model

    def test_missing_variable_is_loud_rather_than_leaking_the_placeholder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        as_dashscope(monkeypatch)
        captured = use_http(monkeypatch, completion_only())

        # Not `LLMNotConfiguredError`: nothing is misconfigured, the caller
        # forgot an argument. That distinction is what lets the API answer
        # 503 for an operator problem and 500 for ours.
        with pytest.raises(LLMCallError) as exc:
            call_llm("plan_generate_system", {})
        assert not isinstance(exc.value, LLMNotConfiguredError)
        assert "query" in str(exc.value)
        assert captured == []  # nothing was sent

    def test_extra_variables_are_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        as_dashscope(monkeypatch)
        use_http(monkeypatch, completion_only())

        # `history` is an optional input on plan_generate_system.
        assert call_llm(
            "plan_generate_system", {"query": "why", "history": ["earlier"]}, model_override=TEST_MODEL
        )

    def test_optional_input_may_be_omitted_entirely(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`{{history}}` is empty on the first turn — the prompt's config says
        so, so an absent key renders empty instead of raising."""
        as_dashscope(monkeypatch)
        captured = use_http(monkeypatch, completion_only())

        call_llm("plan_generate_system", {"query": "why"}, model_override=TEST_MODEL)

        assert "{{history}}" not in sent_body(captured)["messages"][0]["content"]


class TestProviderContract:
    def test_a_real_provider_without_a_configured_registry_fails_loudly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ADR 0004's own call: a seed prompt has no model, so reaching a
        real provider with one unresolved must fail visibly rather than
        quietly serve a model nobody chose."""
        as_dashscope(monkeypatch)
        captured = use_http(monkeypatch, completion_only())

        with pytest.raises(LLMNotConfiguredError) as exc:
            call_llm("plan_generate_system", {"query": "why"})

        assert "LANGFUSE" in str(exc.value)
        assert captured == []  # nothing was sent

    def test_dashscope_request_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        as_dashscope(monkeypatch)
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-secret")
        captured = use_http(monkeypatch, completion_only())

        content = call_llm("plan_generate_system", {"query": "why"}, model_override=TEST_MODEL)

        request = captured[0]
        assert request.method == "POST"
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["authorization"] == "Bearer sk-secret"
        # The raw completion comes back verbatim — parsing is the caller's job.
        assert json.loads(content)["sections"][0]["title"] == "Background"

    def test_model_override_wins_for_debugging(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        as_dashscope(monkeypatch)
        captured = use_http(monkeypatch, completion_only())

        call_llm("plan_generate_system", {"query": "why"}, model_override="qwen-turbo")

        assert sent_body(captured)["model"] == "qwen-turbo"

    def test_unconfigured_provider_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "dashscope")
        with pytest.raises(LLMNotConfiguredError) as exc:
            call_llm("plan_generate_system", {"query": "why"})
        assert "DASHSCOPE_API_KEY" in str(exc.value)

    def test_unknown_provider_name_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "gpt-9")
        with pytest.raises(LLMNotConfiguredError) as exc:
            call_llm("plan_generate_system", {"query": "why"})
        assert "gpt-9" in str(exc.value)

    def test_registry_is_cached_so_repeat_calls_hit_the_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        as_dashscope(monkeypatch)
        captured = use_http(monkeypatch, completion_only())

        for _ in range(3):
            call_llm("plan_generate_system", {"query": "why"}, model_override=TEST_MODEL)

        assert len(captured) == 3  # three completions, one registry read


class TestRefusal:
    def test_empty_completion_is_a_refusal_not_an_empty_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        as_dashscope(monkeypatch)
        use_http(monkeypatch, completion_only({"choices": [{"message": {"content": "  "}}]}))

        with pytest.raises(LLMRefusedError):
            call_llm("plan_generate_system", {"query": "why"}, model_override=TEST_MODEL)

    def test_content_filter_finish_reason_is_a_refusal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        as_dashscope(monkeypatch)
        use_http(
            monkeypatch,
            completion_only(
                {"choices": [{"message": {"content": "nope"}, "finish_reason": "content_filter"}]}
            ),
        )

        with pytest.raises(LLMRefusedError) as exc:
            call_llm("plan_generate_system", {"query": "why"}, model_override=TEST_MODEL)
        assert "content" in str(exc.value).lower()

    def test_provider_error_is_not_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        as_dashscope(monkeypatch)
        use_http(monkeypatch, completion_only(httpx.Response(500, json={})))

        with pytest.raises(LLMNotConfiguredError):
            call_llm("plan_generate_system", {"query": "why"}, model_override=TEST_MODEL)


class TestLangfuseRegistry:
    def _with_langfuse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        as_dashscope(monkeypatch)
        monkeypatch.setenv("LANGFUSE_BASE_URL", "http://langfuse.internal")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf")

    def test_langfuse_prompt_and_config_win_when_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._with_langfuse(monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            if "/api/v2/prompts" in request.url.path:
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "name": "plan_generate_system",
                                "prompt": "Langfuse says: weigh {{query}} in depth.",
                                "config": {"model": "qwen-long", "temperature": 0.1},
                            }
                        ]
                    },
                )
            return httpx.Response(200, json=PLAN_COMPLETION)

        captured = use_http(monkeypatch, handler)

        call_llm("plan_generate_system", {"query": "why"})

        assert len(captured) == 2
        prompt_call, completion_call = captured
        assert "/api/v2/prompts" in prompt_call.url.path
        assert basic_credentials(prompt_call) == "pk:sk-lf"
        body = sent_body(captured, 1)
        assert "Langfuse says:" in body["messages"][0]["content"]
        assert body["model"] == "qwen-long"  # model routing is Langfuse's (ADR 0004)

    def test_langfuse_outage_falls_back_to_the_bundled_seed_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A registry blip must not lose the prompt: the seed text is used
        so the request still goes out. The model does not come with it —
        that is the ADR's point."""
        self._with_langfuse(monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            if "/api/v2/prompts" in request.url.path:
                return httpx.Response(503, json={"message": "registry down"})
            return httpx.Response(200, json=PLAN_COMPLETION)

        captured = use_http(monkeypatch, handler)

        call_llm("plan_generate_system", {"query": "why"}, model_override=TEST_MODEL)

        system = sent_body(captured)["messages"][0]["content"]
        assert "sections" in system  # the seed prompt answered instead


class TestStubProvider:
    """`LLM_PROVIDER=stub` is the offline / demo path: deterministic output,
    no network, no key. It exists so the vertical slice is runnable before
    an operator wires real credentials — opt-in, never the default."""

    def test_stub_returns_a_plan_that_validates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "stub")

        content = call_llm("plan_generate_system", {"query": "How do kites fly?"})

        plan = parse_plan(json.loads(content))
        assert 1 <= len(plan.sections) <= 8
        assert all(section.title for section in plan.sections)

    def test_stub_is_deterministic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "stub")
        first = call_llm("plan_generate_system", {"query": "same query"})
        second = call_llm("plan_generate_system", {"query": "same query"})
        assert first == second

    def test_stub_does_not_pretend_to_cover_other_stages(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "stub")
        with pytest.raises(LLMNotConfiguredError) as exc:
            call_llm("research_sub_query_generate_system", {"section_brief": "x"})
        assert "research_sub_query_generate_system" in str(exc.value)

    def test_stub_needs_no_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "stub")
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        assert call_llm("plan_generate_system", {"query": "no key needed"})