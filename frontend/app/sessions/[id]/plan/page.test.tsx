import { act, render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PlanSummary, SessionState } from "../../../../lib/sessions";
import PlanPage from "./page";

/**
 * The Plan page is the only thing issue #3 puts in front of a user, and
 * its acceptance criterion names four fields: title, brief, sub_questions
 * and note. Testing the pure helpers in `lib/plan.ts` proves the
 * arithmetic; only rendering the page proves those fields reach the DOM.
 *
 * The two seams are stubbed, not the component: `getSessionState` because
 * hitting the network is not what is under test, `useSessionEvents`
 * because it opens a streaming connection. Everything below them is the
 * real page, including the SSE handler it registers.
 */

type StreamEvent = { id: number | null; event: string; data: Record<string, unknown> };

// `vi.mock` factories are hoisted above the imports, so everything they
// close over has to be hoisted with them.
const { handlers, getSessionState } = vi.hoisted(() => ({
  handlers: [] as Array<(event: StreamEvent) => void>,
  getSessionState: vi.fn<(id: string) => Promise<unknown>>(),
}));

vi.mock("../../../../lib/sessions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/sessions")>();
  return { ...actual, getSessionState };
});

vi.mock("../../../../lib/useSessionEvents", () => ({
  useSessionEvents: (_id: string | null, onEvent: (event: StreamEvent) => void) => {
    handlers.push(onEvent);
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

/** Deliver an SSE frame to the page the way the real hook would. */
async function emit(event: StreamEvent) {
  const handler = handlers[handlers.length - 1];
  expect(handler, "the page registered no event handler").toBeDefined();
  await act(async () => {
    handler!(event);
  });
}

function section(over: Partial<PlanSummary["sections"][number]> = {}) {
  return {
    id: "sec-1",
    title: "Background",
    brief: "Establish how the topic developed.",
    sub_questions: ["When did it start?"],
    note: null,
    ...over,
  };
}

function stateWith(plan: PlanSummary | null): SessionState {
  return {
    session: {
      session_id: "s-1",
      query: "why is the sky blue?",
      created_at: "2026-10-20T00:00:00Z",
      updated_at: "2026-10-20T00:00:01Z",
    },
    plan,
    report_md: null,
    latest_event_id: 1,
  };
}

const PLAN: PlanSummary = {
  plan_id: "p-1",
  version: 1,
  approved: false,
  approved_at: null,
  plan_note: null,
  sections: [section()],
};

async function renderPage() {
  // Next 15 hands `params` to a client page as a Promise, which the page
  // unwraps with `use()` — hence the Suspense boundary, as in the app.
  //
  // The whole render sits inside `act()` because two separate async things
  // have to land before there is anything to assert on: the params promise
  // (so `use()` stops suspending) and the page's own `useEffect` fetch
  // (so `setState` commits). Outside `act`, React commits neither and the
  // tree stays on the fallback forever.
  const params = Promise.resolve({ id: "s-1" });
  await act(async () => {
    await params;
    render(
      <Suspense fallback={<p>loading…</p>}>
        <PlanPage params={params} />
      </Suspense>,
    );
  });
}

beforeEach(() => {
  getSessionState.mockReset();
  handlers.length = 0;
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("PlanPage", () => {
  it("renders every Section's four fields", async () => {
    getSessionState.mockResolvedValue(
      stateWith({
        ...PLAN,
        sections: [
          section(),
          section({
            id: "sec-2",
            title: "Open questions",
            brief: "Identify what is still unsettled.",
            sub_questions: ["What is unproven?", "Who disagrees?"],
            note: { text: "Prefer primary sources." },
          }),
        ],
      }),
    );

    await renderPage();

    await screen.findByText("why is the sky blue?");

    // title
    expect(screen.getByRole("heading", { name: "Background" })).toBeDefined();
    expect(screen.getByRole("heading", { name: "Open questions" })).toBeDefined();
    // brief
    expect(screen.getByText("Establish how the topic developed.")).toBeDefined();
    expect(screen.getByText("Identify what is still unsettled.")).toBeDefined();
    // sub_questions
    expect(screen.getByText("When did it start?")).toBeDefined();
    expect(screen.getByText("What is unproven?")).toBeDefined();
    expect(screen.getByText("Who disagrees?")).toBeDefined();
    // note
    expect(screen.getByText(/Prefer primary sources\./)).toBeDefined();
  });

  it("numbers the Sections so their order is visible", async () => {
    getSessionState.mockResolvedValue(
      stateWith({ ...PLAN, sections: [section(), section({ id: "sec-2", title: "Open questions" })] }),
    );

    await renderPage();

    await screen.findByText("why is the sky blue?");
    const indices = screen.getAllByText(/^[12]$/).map((el) => el.textContent);
    expect(indices).toEqual(["1", "2"]);
  });

  it("omits the note element for a Section that has none", async () => {
    getSessionState.mockResolvedValue(stateWith(PLAN));

    await renderPage();

    await screen.findByText("why is the sky blue?");
    expect(screen.queryByText("Note")).toBeNull();
  });

  it("omits the sub-question list when a Section has none", async () => {
    getSessionState.mockResolvedValue(stateWith({ ...PLAN, sections: [section({ sub_questions: [] })] }));

    await renderPage();

    await screen.findByText("why is the sky blue?");
    expect(screen.queryByText("When did it start?")).toBeNull();
    // The brief still renders, so this is not an empty Section.
    expect(screen.getByText("Establish how the topic developed.")).toBeDefined();
  });

  it("shows the version and the awaiting-review state", async () => {
    getSessionState.mockResolvedValue(stateWith(PLAN));

    await renderPage();

    await screen.findByText("why is the sky blue?");
    expect(screen.getByText(/version 1/)).toBeDefined();
    expect(screen.getByText(/awaiting your review/)).toBeDefined();
  });

  it("says so when the Session has no plan yet", async () => {
    getSessionState.mockResolvedValue(stateWith(null));

    await renderPage();

    await screen.findByText("why is the sky blue?");
    expect(screen.getByText("No plan yet.")).toBeDefined();
  });

  it("explains a Session that is not the caller's instead of rendering blank", async () => {
    getSessionState.mockResolvedValue(null);

    await renderPage();

    await screen.findByText(/does not exist, or it is not yours/);
  });
});

describe("PlanPage and the event stream", () => {
  it("re-renders when a plan_ready arrives over SSE", async () => {
    // The page has two inputs on purpose: GET /state paints it, the
    // stream keeps it current. This covers the second.
    getSessionState.mockResolvedValue(stateWith(null));
    await renderPage();
    await screen.findByText("No plan yet.");

    await emit({
      id: 1,
      event: "plan_ready",
      data: {
        plan: {
          plan_id: "p-2",
          version: 2,
          approved: false,
          approved_at: null,
          plan_note: null,
          sections: [section({ title: "Arrived live", brief: "From the stream." })],
        },
      },
    });

    expect(screen.getByRole("heading", { name: "Arrived live" })).toBeDefined();
    expect(screen.getByText("From the stream.")).toBeDefined();
    expect(screen.getByText(/version 2/)).toBeDefined();
  });

  it("ignores an event that is not a plan", async () => {
    // Issue #4 and #5 will push research_progress and report_ready down
    // this same stream; the Plan page must not rewrite itself for them.
    getSessionState.mockResolvedValue(stateWith(PLAN));
    await renderPage();
    await screen.findByText("why is the sky blue?");

    await emit({ id: 2, event: "research_progress", data: { section_index: 0 } });

    expect(screen.getByRole("heading", { name: "Background" })).toBeDefined();
    expect(screen.getByText(/version 1/)).toBeDefined();
  });

  it("ignores a plan_ready that carries no plan", async () => {
    getSessionState.mockResolvedValue(stateWith(PLAN));
    await renderPage();
    await screen.findByText("why is the sky blue?");

    await emit({ id: 3, event: "plan_ready", data: {} });

    expect(screen.getByRole("heading", { name: "Background" })).toBeDefined();
  });
});