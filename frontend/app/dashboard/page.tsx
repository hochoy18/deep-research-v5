"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { PlanRejectedError, createSession } from "../../lib/sessions";
import { useAuth } from "../../lib/useAuth";

/**
 * Where a User Query is typed.
 *
 * The submit button stays disabled while the backend is generating the
 * Plan, because `POST /sessions` is synchronous through `plan_generate`
 * — a second click would start a second Session. When the model declines,
 * the sentence it gave is shown verbatim rather than replaced with a
 * generic failure: that sentence is the only thing the user can act on.
 */
export default function DashboardPage() {
  const router = useRouter();
  const { bearer, whoami, ready, signOut } = useAuth();

  const [query, setQuery] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (ready && !bearer) {
      router.replace("/login");
    }
  }, [ready, bearer, router]);

  if (!ready) {
    return <p className="subtitle">Loading…</p>;
  }

  const submit = async () => {
    const trimmed = query.trim();
    if (!trimmed || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const { sessionId } = await createSession(trimmed);
      router.replace(`/sessions/${sessionId}/plan`);
    } catch (err) {
      if (err instanceof PlanRejectedError) {
        setError(err.reason);
      } else {
        setError(err instanceof Error ? err.message : "Could not start the session.");
      }
      setSubmitting(false);
    }
  };

  return (
    <div className="card wide">
      <h1 className="title">Deep Research{whoami ? `, ${whoami.username}` : ""}</h1>
      <p className="subtitle">
        Ask a question. A structured plan is generated for your review before
        any research runs.
      </p>

      {error && <p className="error">{error}</p>}

      <div className="field">
        <label htmlFor="query">Your question</label>
        <textarea
          id="query"
          rows={4}
          maxLength={2000}
          placeholder="What do you want to understand?"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit();
          }}
        />
      </div>

      <button
        className="btn"
        onClick={() => void submit()}
        disabled={submitting || query.trim().length === 0}
      >
        {submitting ? "Generating plan…" : "Generate plan"}
      </button>

      <button
        className="link-btn"
        onClick={async () => {
          await signOut();
          router.replace("/login");
        }}
      >
        Sign out
      </button>
    </div>
  );
}