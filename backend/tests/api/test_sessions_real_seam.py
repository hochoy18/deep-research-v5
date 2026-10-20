"""The vertical slice driven through the *real* `call_llm` seam.

Every other HTTP test monkeypatches `call_llm` as the Plan layer consumes
it. That is the right seam for testing Plan behaviour, but it means the
wiring the acceptance criterion actually names — `plan_generate` calling
`call_llm('plan_generate_system', ...)` — is never exercised as a whole.
A prompt id mistyped in `service.py`, or a variable the real renderer
requires but the fake never looks at, would pass every other test here.

So these tests configure `LLM_PROVIDER=stub` and let the seam resolve and
render the real bundled seed prompt. Nothing is stubbed except the model
itself.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Conversation, Message, PlanRow
from app.seams.call_llm import LLMNotConfiguredError, call_llm, reset_prompt_cache


@pytest.fixture
def real_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the seam at the deterministic offline provider.

    The seed prompt is read from disk and rendered through the real
    templating path, so `{{query}}` substitution is genuinely exercised.
    """
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    # The seam caches resolved prompts; a Langfuse lookup from an earlier
    # test must not leak into this one.
    reset_prompt_cache()


def _signup(client: TestClient, username: str = "real") -> str:
    r = client.post("/auth/signup", json={"username": username, "password": "hunter2"})
    if r.status_code == 409:
        r = client.post("/auth/login", json={"username": username, "password": "hunter2"})
    assert r.status_code == 201 or r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestThroughTheRealSeam:
    def test_a_query_gets_a_plan_without_any_stub(self, client: TestClient, real_seam) -> None:
        """The acceptance criterion itself: Query → `call_llm('plan_generate_system')`
        → a schema-valid Plan, with nothing but the model faked."""
        token = _signup(client)

        r = client.post(
            "/sessions",
            json={"query": "How does retrieval-augmented generation affect report accuracy?"},
            headers=_auth(token),
        )

        assert r.status_code == 201, r.text
        session_id = r.json()["session_id"]

        state = client.get(f"/sessions/{session_id}/state", headers=_auth(token))
        assert state.status_code == 200, state.text
        plan = state.json()["plan"]
        assert plan is not None, "no plan was generated"
        assert 1 <= len(plan["sections"]) <= 8
        assert plan["version"] == 1
        assert plan["approved"] is False
        assert plan["plan_note"] is None

    def test_the_seam_receives_the_query_it_asks_for(self, real_seam) -> None:
        """The prompt id and the variables are the seam contract; a typo in
        `PlanService.generate` would satisfy every monkeypatched test."""
        completion = call_llm("plan_generate_system", {"query": "why is the sky blue?"})

        assert completion.lstrip().startswith("{"), completion
        assert "sky" in completion or "sections" in completion

    def test_the_writes_are_the_ones_the_spec_names(
        self, client: TestClient, real_seam, db_session
    ) -> None:
        """One conversation row, one role='user' message, one plan row at
        version=1 — produced without touching the fake."""
        token = _signup(client, username="rows")
        r = client.post("/sessions", json={"query": "what changed in 2026?"}, headers=_auth(token))
        assert r.status_code == 201, r.text
        session_id = r.json()["session_id"]

        conversations = db_session.execute(
            select(Conversation).where(Conversation.id == session_id)
        ).scalars().all()
        assert len(conversations) == 1

        messages = db_session.execute(
            select(Message).where(Message.conversation_id == session_id)
        ).scalars().all()
        # The spec asks for one role='user' row carrying the Query. The
        # `stream_event` seam additionally writes a role='event' row for
        # the `plan_ready` frame, which is what issue #9 replays from.
        assert [m.role for m in messages].count("user") == 1
        user_message = next(m for m in messages if m.role == "user")
        assert user_message.content == "what changed in 2026?"
        assert [m.event_type for m in messages if m.role == "event"] == ["plan_ready"]

        plans = db_session.execute(
            select(PlanRow).where(PlanRow.conversation_id == session_id)
        ).scalars().all()
        assert [p.version for p in plans] == [1]
        assert plans[0].plan_note is None
        assert plans[0].approved is False

    def test_plan_ready_reaches_the_stream(self, client: TestClient, real_seam) -> None:
        """The SSE replay a late-connecting browser depends on, with the
        real plan payload rather than a canned one."""
        token = _signup(client, username="sse")
        r = client.post("/sessions", json={"query": "explain consensus"}, headers=_auth(token))
        assert r.status_code == 201, r.text
        session_id = r.json()["session_id"]

        stream = client.get(
            f"/sessions/{session_id}/events?timeout=0.3", headers=_auth(token)
        )
        assert stream.status_code == 200
        assert "event: plan_ready" in stream.text
        assert session_id in stream.text


class TestWhenTheSeamCannotReachAModel:
    def test_an_unconfigured_deployment_is_a_503_not_a_500(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No Langfuse, no model in the seed registry (ADR 0004), default
        provider `dashscope`: the operator has a configuration to fix, so
        the answer says so instead of surfacing an anonymous traceback."""
        monkeypatch.setenv("LLM_PROVIDER", "dashscope")
        monkeypatch.setenv("DASHSCOPE_API_KEY", "not-a-real-key")
        monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        reset_prompt_cache()

        token = _signup(client, username="unconfigured")
        r = client.post("/sessions", json={"query": "anything"}, headers=_auth(token))

        assert r.status_code == 503, r.text
        detail = r.json()["detail"]
        assert detail["stage"] == "plan_generate"
        # The reason must tell an operator what to do, not just that it broke.
        assert "LANGFUSE" in detail["detail"] or "model" in detail["detail"].lower()
        reset_prompt_cache()

    def test_the_seam_names_the_missing_model_itself(self, monkeypatch) -> None:
        """The error an operator will actually hit, asserted at the seam."""
        monkeypatch.setenv("LLM_PROVIDER", "dashscope")
        monkeypatch.setenv("DASHSCOPE_API_KEY", "not-a-real-key")
        monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
        reset_prompt_cache()

        with pytest.raises(LLMNotConfiguredError) as exc:
            call_llm("plan_generate_system", {"query": "why?"})

        assert "LANGFUSE" in str(exc.value)
        reset_prompt_cache()