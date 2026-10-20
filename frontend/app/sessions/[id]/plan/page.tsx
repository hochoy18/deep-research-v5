"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { planHeadline, planStatus } from "../../../../lib/plan";
import {
  getSessionState,
  type PlanSummary,
  type SessionState,
} from "../../../../lib/sessions";
import { useSessionEvents } from "../../../../lib/useSessionEvents";

/**
 * The Plan page — the read half of issue #3.
 *
 * It renders what `plan_generate` produced and nothing else: a Plan to
 * read while the user decides. There are no edit controls here yet; those
 * are issue #4 (edit / approve / reject) and issue #5 (start research).
 *
 * State arrives twice over, deliberately. `GET /state` paints the page on
 * load or refresh, and the SSE stream pushes any later `plan_ready` — so
 * the page survives a refresh without waiting for an event, and still
 * updates when the backend sends one.
 */
export default function PlanPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();

  const [state, setState] = useState<SessionState | null>(null);
  const [plan, setPlan] = useState<PlanSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getSessionState(id)
      .then((loaded) => {
        if (cancelled) return;
        if (loaded === null) {
          setError("That session does not exist, or it is not yours.");
          setReady(true);
          return;
        }
        setState(loaded);
        setPlan(loaded.plan);
        setReady(true);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Could not load this session.");
        setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  useSessionEvents(id, (event) => {
    if (event.event !== "plan_ready") return;
    const next = event.data.plan as PlanSummary | undefined;
    if (next) setPlan(next);
  });

  if (!ready) {
    return <p className="subtitle">Loading…</p>;
  }

  if (error) {
    return (
      <div className="card wide">
        <p className="error">{error}</p>
        <button className="btn" onClick={() => router.replace("/dashboard")}>
          Back to dashboard
        </button>
      </div>
    );
  }

  const status = planStatus(plan);

  return (
    <div className="card wide">
      <button className="link-btn" onClick={() => router.replace("/dashboard")}>
        ← New research
      </button>

      <h1 className="title">{state?.session.query}</h1>
      <p className="subtitle">
        {planHeadline(plan)}
        {status === "approved" ? " · approved" : " · awaiting your review"}
      </p>

      {plan === null ? (
        <p className="subtitle">No plan yet.</p>
      ) : (
        <ol className="sections">
          {plan.sections.map((section, index) => (
            <li key={section.id} className="section">
              <div className="section-head">
                <span className="section-index">{index + 1}</span>
                <h2 className="section-title">{section.title}</h2>
              </div>
              <p className="section-brief">{section.brief}</p>

              {section.sub_questions.length > 0 && (
                <ul className="sub-questions">
                  {section.sub_questions.map((question) => (
                    <li key={question}>{question}</li>
                  ))}
                </ul>
              )}

              {section.note && (
                <p className="note">
                  <span className="note-label">Note</span> {section.note.text}
                </p>
              )}
            </li>
          ))}
        </ol>
      )}

      {status === "awaiting_review" && plan !== null && (
        <p className="hint">
          Editing and approving the plan arrive in the next ticket.
        </p>
      )}
    </div>
  );
}