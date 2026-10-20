/**
 * View helpers for a Plan.
 *
 * Issue #3 renders the Plan read-only, so these are pure functions over
 * the payload the API returns: no fetch, no React, no state. Keeping them
 * here is what lets the Plan page be tested by asserting on strings
 * rather than on rendered markup.
 */

import type { PlanSummary } from "./sessions";

export type PlanStatus = "none" | "awaiting_review" | "approved";

/** Which badge the Plan page shows. `awaiting_review` is the state issue #3
 * leaves every Session in — the graph is parked on `plan_wait_human`. */
export function planStatus(plan: PlanSummary | null): PlanStatus {
  if (!plan) return "none";
  return plan.approved ? "approved" : "awaiting_review";
}

export function sectionCount(plan: PlanSummary | null): number {
  return plan?.sections.length ?? 0;
}

export function subQuestionCount(plan: PlanSummary | null): number {
  return plan?.sections.reduce((sum, s) => sum + s.sub_questions.length, 0) ?? 0;
}

/** The one-line summary under the query: "2 sections · 2 sub-questions ·
 * version 1". Singular forms are worth the branch — "1 sub-questions"
 * reads like a bug in the UI. */
export function planHeadline(plan: PlanSummary | null): string {
  if (!plan) return "";
  const sections = plural(plan.sections.length, "section");
  const questions = plural(subQuestionCount(plan), "sub-question");
  return `${sections} · ${questions} · version ${plan.version}`;
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}