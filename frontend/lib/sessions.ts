/**
 * Session client — submit a Query, read a Session's state.
 *
 * Split from `api.ts` because the Session endpoints carry a vocabulary
 * the auth endpoints do not (Plans, Sections, a 422 that means "the model
 * declined"), and because the types here are shared with the Plan page.
 *
 * The refusal path is the reason this module exists rather than another
 * function in `api.ts`: a 422 from `POST /sessions` carries the model's
 * own sentence in `detail.reason`, and that sentence is the whole point of
 * the response. It reaches the user as `PlanRejectedError.reason`.
 */

import { apiUrl, authHeader } from "./backend";

export type PlanSection = {
  id: string;
  title: string;
  brief: string;
  sub_questions: string[];
  /** A Section-level Note; null until a human writes one (issue #4). */
  note: { text: string } | null;
};

export type PlanSummary = {
  plan_id: string;
  version: number;
  approved: boolean;
  approved_at: string | null;
  plan_note: string | null;
  sections: PlanSection[];
};

/** The Session itself. CONTEXT.md: "Session" is the frontend-facing term;
 * the `conversations` table is the persistence term and never appears here. */
export type SessionSummary = {
  session_id: string;
  query: string;
  created_at: string;
  updated_at: string;
};

export type SessionState = {
  session: SessionSummary;
  plan: PlanSummary | null;
  report_md: string | null;
  latest_event_id: number;
};

export type Violation = { field: string; message: string };

/** The model declined, or answered outside the Plan schema. */
export class PlanRejectedError extends Error {
  readonly reason: string;
  readonly stage: string;
  readonly violations: Violation[];

  constructor(reason: string, stage: string, violations: Violation[]) {
    super(reason);
    this.name = "PlanRejectedError";
    this.reason = reason;
    this.stage = stage;
    this.violations = violations;
  }
}

/** Start a Session. Resolves once the backend has generated the Plan. */
export async function createSession(
  query: string,
): Promise<{ sessionId: string }> {
  const res = await fetch(apiUrl("/sessions"), {
    method: "POST",
    headers: { "content-type": "application/json", ...authHeader() },
    body: JSON.stringify({ query }),
  });

  if (res.status === 422) {
    throw await readRejection(res);
  }
  await ensureOk(res);
  const body = (await res.json()) as { session_id: string };
  return { sessionId: body.session_id };
}

/** The current snapshot, or null when the Session is not the caller's. */
export async function getSessionState(sessionId: string): Promise<SessionState | null> {
  const res = await fetch(apiUrl(`/sessions/${sessionId}/state`), {
    headers: authHeader(),
  });
  // A 404 is "nothing to render here", not a failure worth interrupting
  // the user over; the caller renders the empty state.
  if (res.status === 404) return null;
  await ensureOk(res);
  return (await res.json()) as SessionState;
}

async function readRejection(res: Response): Promise<PlanRejectedError> {
  let detail: unknown;
  try {
    detail = (await res.json()) as { detail?: unknown };
  } catch {
    return new PlanRejectedError(res.statusText || "the plan was rejected", "plan_generate", []);
  }
  const body = (detail as { detail?: unknown }).detail;
  if (typeof body === "string") {
    return new PlanRejectedError(body, "plan_generate", []);
  }
  const record = (body ?? {}) as Partial<PlanRejectedError>;
  return new PlanRejectedError(
    record.reason ?? "the plan could not be generated",
    record.stage ?? "plan_generate",
    record.violations ?? [],
  );
}

async function ensureOk(res: Response): Promise<void> {
  if (res.ok) return;
  const detail = await readError(res);
  const error = new Error(detail) as Error & { status?: number };
  error.status = res.status;
  throw error;
}

async function readError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: string };
    return body.detail ?? res.statusText;
  } catch {
    return res.statusText;
  }
}