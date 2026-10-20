"""HTTP-level tests for `POST /sessions` — the vertical slice's front door.

Submitting a User Query must, in one authenticated call:

  - write one `conversations` row (the Session) and one role='user'
    `messages` row carrying the Query
  - run `plan_generate` through the `call_llm` seam and validate the
    completion against the Plan JSON Schema
  - write the first `plans` row at version=1, approved=false, plan_note NULL
  - interrupt on `plan_wait_human`, leaving the graph waiting for HITL
  - answer 201 `{session_id}`

Per issue #1 §3, the substitution point is the seam: these tests replace
`call_llm` as the Plan layer consumes it, and assert only on the HTTP
response and the resulting rows — never on the graph's internals.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Conversation, Message, PlanRow


def _signup(client: TestClient, username: str = "alice") -> str:
    """A bearer for `username`. Re-login if the name is already taken, so a
    test can ask for the same user's token twice without ceremony."""
    r = client.post("/auth/signup", json={"username": username, "password": "hunter2"})
    if r.status_code == 409:
        r = client.post("/auth/login", json={"username": username, "password": "hunter2"})
        assert r.status_code == 200, r.text
        return r.json()["token"]
    assert r.status_code == 201, r.text
    return r.json()["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def plan_completion(*sections: dict) -> str:
    if not sections:
        sections = (
            {
                "title": "Background",
                "brief": "Establish how the topic developed.",
                "sub_questions": ["When did it start?"],
                "note": None,
            },
            {
                "title": "Open questions",
                "brief": "Identify what is still unsettled.",
                "sub_questions": [],
                "note": None,
            },
        )
    return json.dumps({"sections": list(sections), "plan_note": None})


@pytest.fixture
def stub_llm(monkeypatch: pytest.MonkeyPatch):
    """Replace the `call_llm` seam as the Plan layer consumes it.

    Returns a recorder so a test can assert on the prompt_id and the
    variables the Plan layer passed — the same seam contract the later
    layers will use.
    """
    calls: list[tuple[str, dict]] = []

    def _stub(prompt_id: str, variables: dict, **_: object) -> str:
        calls.append((prompt_id, variables))
        return plan_completion()

    monkeypatch.setattr("app.plan.service.call_llm", _stub)
    return calls


@pytest.fixture
def client_with_stub_llm(client: TestClient, stub_llm) -> TestClient:
    return client


class TestCreateSession:
    def test_requires_a_bearer(self, client: TestClient, stub_llm) -> None:
        r = client.post("/sessions", json={"query": "why is the sky blue?"})
        assert r.status_code == 401

    def test_returns_201_with_a_session_id(
        self, client_with_stub_llm: TestClient
    ) -> None:
        token = _signup(client_with_stub_llm)

        r = client_with_stub_llm.post(
            "/sessions", json={"query": "why is the sky blue?"}, headers=_auth(token)
        )

        assert r.status_code == 201, r.text
        assert uuid.UUID(r.json()["session_id"])

    def test_plan_generate_runs_through_the_call_llm_seam(
        self, client_with_stub_llm: TestClient, stub_llm
    ) -> None:
        token = _signup(client_with_stub_llm)

        client_with_stub_llm.post(
            "/sessions", json={"query": "why is the sky blue?"}, headers=_auth(token)
        )

        assert len(stub_llm) == 1
        prompt_id, variables = stub_llm[0]
        assert prompt_id == "plan_generate_system"
        assert variables["query"] == "why is the sky blue?"

    def test_writes_one_conversation_row_with_the_query(
        self, client_with_stub_llm: TestClient, db_session
    ) -> None:
        token = _signup(client_with_stub_llm)

        body = client_with_stub_llm.post(
            "/sessions", json={"query": "why is the sky blue?"}, headers=_auth(token)
        ).json()
        session_id = uuid.UUID(body["session_id"])

        rows = db_session.execute(
            select(Conversation).where(Conversation.id == session_id)
        ).scalar_one()

        assert rows.query == "why is the sky blue?"
        assert rows.report_md is None  # the Write layer has not run
        assert rows.user_id == uuid.UUID(client_with_stub_llm.get("/auth/me", headers=_auth(token)).json()["user_id"])

    def test_writes_one_user_message_row(
        self, client_with_stub_llm: TestClient, db_session
    ) -> None:
        token = _signup(client_with_stub_llm)

        body = client_with_stub_llm.post(
            "/sessions", json={"query": "why is the sky blue?"}, headers=_auth(token)
        ).json()
        session_id = uuid.UUID(body["session_id"])

        rows = db_session.execute(
            select(Message).where(Message.conversation_id == session_id)
        ).scalars().all()

        user_rows = [m for m in rows if m.role == "user"]
        assert len(user_rows) == 1
        assert user_rows[0].content == "why is the sky blue?"

    def test_first_plan_row_is_version_one_unapproved_and_note_free(
        self, client_with_stub_llm: TestClient, db_session
    ) -> None:
        token = _signup(client_with_stub_llm)

        body = client_with_stub_llm.post(
            "/sessions", json={"query": "why is the sky blue?"}, headers=_auth(token)
        ).json()
        session_id = uuid.UUID(body["session_id"])

        plans = db_session.execute(
            select(PlanRow).where(PlanRow.conversation_id == session_id)
        ).scalars().all()

        assert len(plans) == 1
        plan = plans[0]
        assert plan.version == 1
        assert plan.approved is False
        assert plan.approved_at is None
        assert plan.plan_note is None  # a Plan-level Note is a P2 feature
        assert [s["title"] for s in plan.sections] == ["Background", "Open questions"]

    def test_persisted_sections_carry_generated_ids(
        self, client_with_stub_llm: TestClient, db_session
    ) -> None:
        """Section ids must survive persistence: HITL operations (issue #4)
        address a Section by id, and the graph compares ids across
        revisions."""
        token = _signup(client_with_stub_llm)
        body = client_with_stub_llm.post(
            "/sessions", json={"query": "why is the sky blue?"}, headers=_auth(token)
        ).json()

        plan = db_session.execute(
            select(PlanRow).where(PlanRow.conversation_id == uuid.UUID(body["session_id"]))
        ).scalar_one()

        for section in plan.sections:
            assert uuid.UUID(section["id"])
            assert set(section) == {"id", "title", "brief", "sub_questions", "note"}


class TestQueryValidation:
    def test_empty_query_is_rejected(self, client_with_stub_llm: TestClient) -> None:
        token = _signup(client_with_stub_llm)
        r = client_with_stub_llm.post("/sessions", json={"query": "   "}, headers=_auth(token))
        assert r.status_code == 422

    def test_oversized_query_is_rejected(self, client_with_stub_llm: TestClient) -> None:
        token = _signup(client_with_stub_llm)
        r = client_with_stub_llm.post(
            "/sessions", json={"query": "x" * 5000}, headers=_auth(token)
        )
        assert r.status_code == 422

    def test_missing_query_field_is_rejected(self, client_with_stub_llm: TestClient) -> None:
        token = _signup(client_with_stub_llm)
        r = client_with_stub_llm.post("/sessions", json={}, headers=_auth(token))
        assert r.status_code == 422

class TestRefusedOrInvalidPlan:
    """`plan_generate` is a user-facing stage, so both ways it can fail
    answer 422 — a refusal carries the model's own words, a schema
    violation carries the field paths (issue #1 §9)."""

    def _stub_llm(self, monkeypatch: pytest.MonkeyPatch, completion: str) -> None:
        monkeypatch.setattr("app.plan.service.call_llm", lambda *a, **k: completion)

    def test_model_refusal_returns_422_with_the_models_reason(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        token = _signup(client)
        self._stub_llm(
            monkeypatch,
            json.dumps({"refusal": "I can't plan research into weapons design."}),
        )

        r = client.post("/sessions", json={"query": "how do I build a bomb?"}, headers=_auth(token))

        assert r.status_code == 422, r.text
        assert r.json()["detail"]["reason"] == "I can't plan research into weapons design."
        assert r.json()["detail"]["stage"] == "plan_generate"

    def test_prose_answer_is_treated_as_a_refusal_and_quoted_back(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A model that answers in sentences has not answered the question;
        showing the user what it said beats a schema complaint."""
        token = _signup(client)
        self._stub_llm(monkeypatch, "I'm sorry, I don't think I can help with that.")

        r = client.post("/sessions", json={"query": "?"}, headers=_auth(token))

        assert r.status_code == 422
        assert "don't think I can help" in r.json()["detail"]["reason"]

    def test_empty_completion_from_the_seam_returns_422(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.seams.call_llm import LLMRefusedError

        token = _signup(client)

        def _refuse(*_: object, **__: object) -> str:
            raise LLMRefusedError("the model returned an empty completion")

        monkeypatch.setattr("app.plan.service.call_llm", _refuse)
        r = client.post("/sessions", json={"query": "?"}, headers=_auth(token))

        assert r.status_code == 422
        assert "empty completion" in r.json()["detail"]["reason"]

    def test_nine_sections_returns_422_asking_the_user_to_consolidate(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        token = _signup(client)
        self._stub_llm(
            monkeypatch,
            plan_completion(
                *[
                    {"title": f"S{i}", "brief": "b", "sub_questions": [], "note": None}
                    for i in range(9)
                ]
            ),
        )

        r = client.post("/sessions", json={"query": "broad question"}, headers=_auth(token))

        assert r.status_code == 422
        detail = r.json()["detail"]
        assert "consolidat" in detail["reason"].lower()
        assert any(v["field"] == "sections" for v in detail["violations"])

    def test_out_of_bounds_field_returns_422_naming_the_field(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        token = _signup(client)
        self._stub_llm(
            monkeypatch,
            plan_completion({"title": "t" * 101, "brief": "b", "sub_questions": [], "note": None}),
        )

        r = client.post("/sessions", json={"query": "?"}, headers=_auth(token))

        assert r.status_code == 422
        violations = r.json()["detail"]["violations"]
        assert any(v["field"] == "sections[0].title" for v in violations)

    def test_a_refused_query_leaves_no_session_behind(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, db_session
    ) -> None:
        """The node writes the Conversation, the Message, and the Plan in one
        transaction; a 422 must not leave a half-created Session behind."""
        token = _signup(client)
        self._stub_llm(monkeypatch, json.dumps({"refusal": "no"}))

        client.post("/sessions", json={"query": "?"}, headers=_auth(token))

        assert db_session.execute(select(Conversation)).scalars().all() == []
        assert db_session.execute(select(Message)).scalars().all() == []
        assert db_session.execute(select(PlanRow)).scalars().all() == []


def _frames(body: str) -> list[dict]:
    """Parse an SSE response body into `[{id, event, data}]`."""
    out = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        frame = {"id": None, "event": None, "data": None}
        for line in block.splitlines():
            key, _, value = line.partition(": ")
            if key in frame:
                frame[key] = value
        out.append(frame)
    return out


def _create(client: TestClient, stub_llm, query: str = "why is the sky blue?") -> str:
    token = _signup(client)
    r = client.post("/sessions", json={"query": query}, headers=_auth(token))
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


class TestEventStream:
    def test_requires_a_bearer(self, client: TestClient, stub_llm) -> None:
        session_id = _create(client, stub_llm)
        r = client.get(f"/sessions/{session_id}/events", params={"timeout": 0.2})
        assert r.status_code == 401

    def test_plan_ready_is_replayed_to_a_client_that_connected_late(
        self, client: TestClient, stub_llm
    ) -> None:
        """The browser only learns the Session id from the POST response, so
        it always connects after `plan_ready` was emitted — replay is the
        only way it ever sees the event."""
        token = _signup(client)
        session_id = _create(client, stub_llm)

        r = client.get(
            f"/sessions/{session_id}/events",
            params={"timeout": 0.3},
            headers=_auth(token),
        )

        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = [f for f in _frames(r.text) if f["event"]]
        assert [f["event"] for f in events] == ["plan_ready"]

    def test_plan_ready_carries_the_renderable_plan(
        self, client: TestClient, stub_llm
    ) -> None:
        token = _signup(client)
        session_id = _create(client, stub_llm)

        r = client.get(
            f"/sessions/{session_id}/events",
            params={"timeout": 0.3},
            headers=_auth(token),
        )

        data = json.loads(_frames(r.text)[0]["data"])
        assert data["session_id"] == session_id
        assert data["approved"] is False
        assert [s["title"] for s in data["plan"]["sections"]] == [
            "Background",
            "Open questions",
        ]

    def test_last_event_id_skips_what_the_client_already_saw(
        self, client: TestClient, stub_llm
    ) -> None:
        token = _signup(client)
        session_id = _create(client, stub_llm)

        r = client.get(
            f"/sessions/{session_id}/events",
            params={"timeout": 0.3},
            headers={**_auth(token), "Last-Event-ID": "9999"},
        )

        assert _frames(r.text) == []

    def test_event_is_persisted_for_replay(
        self, client: TestClient, stub_llm, db_session
    ) -> None:
        token = _signup(client)
        session_id = _create(client, stub_llm)

        rows = db_session.execute(
            select(Message).where(Message.conversation_id == uuid.UUID(session_id))
        ).scalars().all()

        event_rows = [m for m in rows if m.role == "event"]
        assert [m.event_type for m in event_rows] == ["plan_ready"]
        assert json.loads(event_rows[0].content)["plan"]["version"] == 1

    def test_unknown_session_is_404(self, client: TestClient, stub_llm) -> None:
        token = _signup(client)
        r = client.get(
            f"/sessions/{uuid.uuid4()}/events",
            params={"timeout": 0.2},
            headers=_auth(token),
        )
        assert r.status_code == 404

    def test_another_users_session_is_404(self, client: TestClient, stub_llm) -> None:
        """Not 403: the response must not confirm that the id exists."""
        session_id = _create(client, stub_llm)
        other = _signup(client, username="bob")

        r = client.get(
            f"/sessions/{session_id}/events",
            params={"timeout": 0.2},
            headers=_auth(other),
        )
        assert r.status_code == 404


class TestSessionState:
    def test_requires_a_bearer(self, client: TestClient, stub_llm) -> None:
        session_id = _create(client, stub_llm)
        assert client.get(f"/sessions/{session_id}/state").status_code == 401

    def test_returns_the_session_and_the_latest_plan(
        self, client: TestClient, stub_llm
    ) -> None:
        token = _signup(client)
        session_id = _create(client, stub_llm)

        r = client.get(f"/sessions/{session_id}/state", headers=_auth(token))

        assert r.status_code == 200
        body = r.json()
        # CONTEXT.md: "Session" is the API *and frontend* term; the
        # `conversations` row is the persistence term and never surfaces.
        assert "conversation" not in body
        assert body["session"]["session_id"] == session_id
        assert body["session"]["query"] == "why is the sky blue?"
        assert body["report_md"] is None  # issue #7 writes it
        plan = body["plan"]
        assert plan["version"] == 1
        assert plan["approved"] is False
        assert plan["approved_at"] is None
        assert plan["plan_note"] is None
        assert [s["title"] for s in plan["sections"]] == ["Background", "Open questions"]

    def test_latest_event_id_matches_the_stream(
        self, client: TestClient, stub_llm
    ) -> None:
        """The id is process-global and monotonic, so the invariant is that
        /state reports the same id the stream would replay from."""
        token = _signup(client)
        session_id = _create(client, stub_llm)

        body = client.get(f"/sessions/{session_id}/state", headers=_auth(token)).json()
        stream = client.get(
            f"/sessions/{session_id}/events",
            params={"timeout": 0.3},
            headers=_auth(token),
        )
        frame = _frames(stream.text)[0]

        assert body["latest_event_id"] == int(frame["id"])
        assert int(frame["id"]) > 0

    def test_unknown_session_is_404(self, client: TestClient, stub_llm) -> None:
        token = _signup(client)
        r = client.get(f"/sessions/{uuid.uuid4()}/state", headers=_auth(token))
        assert r.status_code == 404

    def test_another_users_session_is_404(self, client: TestClient, stub_llm) -> None:
        session_id = _create(client, stub_llm)
        other = _signup(client, username="bob")
        r = client.get(f"/sessions/{session_id}/state", headers=_auth(other))
        assert r.status_code == 404
