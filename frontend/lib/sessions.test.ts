import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { API_BASE } from "./backend";
import { writeBearer } from "./bearer";
import { PlanRejectedError, createSession, getSessionState } from "./sessions";

/**
 * The Session client is what turns a typed Query into a running Session,
 * and it is where a model refusal has to arrive at the user intact — the
 * backend's 422 carries the model's own sentence in `detail.reason`, and
 * the UI shows exactly that. Swallowing it into "request failed" would
 * throw away the only sentence the user can act on.
 */

function mockFetch(response: Response | Promise<Response>) {
  const spy = vi.fn().mockReturnValue(Promise.resolve(response));
  vi.stubGlobal("fetch", spy);
  return spy;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

beforeEach(() => {
  window.localStorage.clear();
  writeBearer({ token: "t-1", userId: "u-1" });
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("createSession", () => {
  it("posts the query with the bearer and returns the session id", async () => {
    const spy = mockFetch(json({ session_id: "s-1" }, 201));

    const result = await createSession("why is the sky blue?");

    expect(result).toEqual({ sessionId: "s-1" });
    const [url, init] = spy.mock.calls[0];
    expect(url).toBe(`${API_BASE}/sessions`);
    expect(init.method).toBe("POST");
    expect(init.headers.authorization).toBe("Bearer t-1");
    expect(JSON.parse(init.body)).toEqual({ query: "why is the sky blue?" });
  });

  it("raises PlanRejectedError carrying the model's own reason", async () => {
    mockFetch(
      json(
        {
          detail: {
            reason: "I can't plan research into weapons design.",
            stage: "plan_generate",
            violations: [],
          },
        },
        422,
      ),
    );

    const error = await createSession("how do I build a bomb?").catch((e) => e);

    expect(error).toBeInstanceOf(PlanRejectedError);
    expect((error as PlanRejectedError).reason).toBe(
      "I can't plan research into weapons design.",
    );
    expect((error as PlanRejectedError).stage).toBe("plan_generate");
  });

  it("carries schema violations when the plan was out of bounds", async () => {
    mockFetch(
      json(
        {
          detail: {
            reason: "sections[0].title is too long",
            stage: "plan_generate",
            violations: [{ field: "sections[0].title", message: "too long" }],
          },
        },
        422,
      ),
    );

    const error = (await createSession("x").catch((e) => e)) as PlanRejectedError;

    expect(error.violations).toEqual([{ field: "sections[0].title", message: "too long" }]);
  });

  it("still raises PlanRejectedError when the body has no reason", async () => {
    mockFetch(json({ detail: "unprocessable" }, 422));

    const error = (await createSession("x").catch((e) => e)) as PlanRejectedError;

    expect(error.reason).toBe("unprocessable");
  });

  it("reports a missing bearer as an auth error", async () => {
    window.localStorage.clear();

    const error = await createSession("x").catch((e) => e);

    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toMatch(/bearer/i);
  });

  it("surfaces a non-422 failure with its status", async () => {
    mockFetch(json({ detail: "boom" }, 500));

    const error = await createSession("x").catch((e) => e);

    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe("boom");
    expect((error as { status?: number }).status).toBe(500);
  });
});

describe("getSessionState", () => {
  it("reads the session and its plan", async () => {
    const spy = mockFetch(
      json({
        session: {
          session_id: "s-1",
          query: "why is the sky blue?",
          created_at: "2026-10-20T00:00:00Z",
          updated_at: "2026-10-20T00:00:01Z",
        },
        plan: {
          plan_id: "p-1",
          version: 1,
          approved: false,
          approved_at: null,
          plan_note: null,
          sections: [],
        },
        report_md: null,
        latest_event_id: 1,
      }),
    );

    const state = await getSessionState("s-1");

    expect(spy.mock.calls[0][0]).toBe(`${API_BASE}/sessions/s-1/state`);
    expect(spy.mock.calls[0][1].headers.authorization).toBe("Bearer t-1");
    expect(state).not.toBeNull();
    expect(state!.session.query).toBe("why is the sky blue?");
    expect(state!.plan?.version).toBe(1);
    expect(state!.report_md).toBeNull();
  });

  it("treats a 404 as 'not there' rather than an error to show", async () => {
    mockFetch(json({ detail: "session not found" }, 404));

    await expect(getSessionState("missing")).resolves.toBeNull();
  });
});