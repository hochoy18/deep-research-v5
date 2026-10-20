import { describe, expect, it } from "vitest";

import type { PlanSummary } from "./sessions";
import { planStatus, planHeadline, sectionCount, subQuestionCount } from "./plan";

/**
 * The Plan page is read-only in issue #3, so everything it decides —
 * which badge to show, how many questions a Plan will research, what the
 * one-line summary says — is a pure function of the plan payload. Those
 * decisions are what the tests pin.
 */

const plan: PlanSummary = {
  plan_id: "11111111-1111-1111-1111-111111111111",
  version: 1,
  approved: false,
  approved_at: null,
  plan_note: null,
  sections: [
    {
      id: "s1",
      title: "Background",
      brief: "How the topic developed.",
      sub_questions: ["When did it start?", "Who were the first actors?"],
      note: null,
    },
    {
      id: "s2",
      title: "Open questions",
      brief: "What is still unsettled.",
      sub_questions: [],
      note: { text: "Needs a source with a 2024 cutoff." },
    },
  ],
};

describe("planStatus", () => {
  it("reads an unapproved plan as awaiting review", () => {
    expect(planStatus(plan)).toBe("awaiting_review");
  });

  it("reads an approved plan as approved", () => {
    expect(planStatus({ ...plan, approved: true })).toBe("approved");
  });

  it("has no status for a missing plan", () => {
    expect(planStatus(null)).toBe("none");
  });
});

describe("sectionCount", () => {
  it("counts the sections", () => {
    expect(sectionCount(plan)).toBe(2);
  });

  it("counts zero for a missing plan", () => {
    expect(sectionCount(null)).toBe(0);
  });
});

describe("subQuestionCount", () => {
  it("sums sub-questions across sections", () => {
    expect(subQuestionCount(plan)).toBe(2);
  });

  it("sums to zero for a missing plan", () => {
    expect(subQuestionCount(null)).toBe(0);
  });
});

describe("planHeadline", () => {
  it("states the shape of the plan", () => {
    expect(planHeadline(plan)).toBe("2 sections · 2 sub-questions · version 1");
  });

  it("counts a zero sub-question section honestly", () => {
    expect(planHeadline({ ...plan, sections: [plan.sections[1]], version: 3 })).toBe(
      "1 section · 0 sub-questions · version 3",
    );
  });

  it("uses the singular for exactly one sub-question", () => {
    const single = { ...plan.sections[0], sub_questions: ["When did it start?"] };
    expect(planHeadline({ ...plan, sections: [single] })).toBe(
      "1 section · 1 sub-question · version 1",
    );
  });

  it("has nothing to say about a missing plan", () => {
    expect(planHeadline(null)).toBe("");
  });
});