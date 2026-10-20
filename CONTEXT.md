# Context — Deep Research Agent v5

Shared glossary for the deep-research agent project. Implementation choices live in `docs/adr/`, not here.

## Concepts

### Deep Research Agent
The whole system. A logged-in **User** enters a User Query, plans it with them (HITL), gathers Sources from the web, and writes a cited Report.

### User
A registered account identified by **username + password**. P1 auth is intentionally minimal — signup, login, JWT bearer, logout. P1 does NOT include password reset, email, 2FA, OAuth, or refresh tokens. Production-grade auth (OAuth) replaces this in P3.

### User Query
The natural-language question, topic, or research goal the user enters at the start.

### Session
A running instance of work driven by a User Query. The API name (`POST /sessions`, `GET /sessions/{id}/state`, etc.) — the user-facing and frontend-facing concept. One Session carries the Plan refinement, Research, and Write stages for a single User Query.

### Conversation
The persistent record of a Session, stored in `app_db.conversations` with the same id. Carries the original `query`, the `report_md` (once written), and links to all `plans` revisions. The 30-day retention clock in "Conversation Lifetime" below counts from this record's `updated_at`.

**Session ↔ Conversation**: 1:1, same UUID. "Session" is the runtime / API term; "Conversation" is the persistence term.

### Plan Layer
First stage. Takes the User Query, produces a Structured Plan, and waits for the user to approve or edit it.

### Structured Plan (a.k.a. "Plan")
A list of Sections, ordered, representing the threads of research to conduct. The user approves or edits the Plan before the Research Layer runs.

**Format**: JSON Schema (typed envelope). Field-level schema:

```
Plan {
  id:           UUID
  version:      int                    // bumped on every edit
  sections:     Section[]              // 1–8 items
  approved:     bool
  approved_at:  timestamp | null
  created_at:   timestamp
  updated_at:   timestamp
}

Section {
  id:            UUID
  title:         string                 // 1–100 chars
  brief:         string                 // 1–500 chars
  sub_questions: string[]               // 0–5 items, each ≤200 chars
  note:          Note | null            // optional Section-level Note
}

Note {
  text:          string                 // 1–1000 chars
}
```

Plans are created, edited, and consumed in this structured form throughout the system — not free-form markdown. Per-field validation lives in the schema code (Pydantic or equivalent).

### Section
One bounded research thread in a Plan. Has:
- title — short label
- brief — 1–2 sentences describing what to investigate
- sub_questions — optional list of decomposed questions
- note — optional user Note attached to this Section

See `Structured Plan` for full field schema and bounds.

### Note
A free-form user message attached to a Section (or, in P2+, optionally to the whole Plan). The text is **injected into the Research layer's `sub_query_generate` prompt** for that Section — the user's intent is meant to influence search.

### HITL (Human-in-the-Loop)
The user reviews the Plan. Five operations are allowed:
- ✅ **Approve** — accept the Plan as-is, advance to Research. Sets `plan.approved = true`.
- ✏️ **Edit** — change title, brief, sub_questions, or note of any Section.
- ➕ **Add Section** — append a new Section.
- ➖ **Remove** — delete a Section.
- 💬 **Note** *(P1: Section-level only; P2+: also Plan-level)* — add or edit the free-form Note on a Section.

**Edit rule** (P1): `Edit` / `Add` / `Remove` / `Note` are **rejected (HTTP 422)** once `plan.approved == true`. Approve flips a latch; concurrent-edit races resolve at HTTP order — first action wins.

### Research Layer
Second stage. For each Section: generates Sub-queries, runs web search, runs an Evaluation, and collects Sources.

**Source deduplication**: Sources are deduplicated **globally by URL** across the whole Session. If two sub-queries return the same URL, it appears once in the aggregated Sources and is cited once in the Report.

**Sub-query generation failure**: the LLM's generated sub-queries are validated (1–5 unique non-empty strings, each ≤200 chars). Invalid output retries up to 3 times; on the 4th miss the entire Section brief is used as the single sub-query (best-effort fallback).

### Sub-query
A web-searchable question, generated from a Section by the Research Layer (or taken directly from `section.sub_questions` if provided).

### Source
One search result: `{ url, title, snippet, optionally full fetched content }`. Cited from the Report by number. **Globally deduplicated by URL** within a Session.

### Evaluation (Research Layer)
A two-tier check on Research results:
- **Per-sub-query** — relevance, source authority, conflict detection. Failing → retry the same sub-query up to N times; on the (N+1)-th miss, proceed with a flag.
- **Whole-plan** — coverage of all Sections. Failing → generate one additional sub-query for the gap, then proceed.

The frontend shows only "Searching…" during retries; retry counts are not exposed.

**Retry cap (N)**: design default is **2**. Per-phase overrides live in `docs/milestones.md` — P1 uses **1** (lighter start), P2/P3 use the design default of 2.

### Write Layer
Third stage. Produces a Report from the approved Plan + gathered Sources.

### Report
Markdown output, structured as:
- **TL;DR** — 3–5 bullets
- **Sections** — one per Plan Section
- **Inline Citations** — `[1][2]`-style references inside Section prose
- **Sources Appendix** — numbered list of all Sources used

Default length: ~3–5 pages.

### Citation
An inline reference such as `[1]` in the Report body, resolved against the Sources Appendix.

**Numbering**: **Globally continuous across the whole Report** (1, 2, 3, …, N) — not per-Section. Each `[n]` maps to exactly one Source in the Sources Appendix; one Source entry cannot appear under two different numbers.

## Layers at a glance

| Layer | Input | Output | HITL? |
|---|---|---|---|
| Plan | User Query | Structured Plan | Yes |
| Research | Approved Plan | Sources | No |
| Write | Plan + Sources | Report | No |

## Vertical-Slice Milestones

Each phase ships a thin version of *every* layer end-to-end. Later phases deepen specific layers, not extend sideways.

See `docs/adr/0001-vertical-slice-staging.md`.

## External systems

- **LangGraph** — agent state-machine orchestration.
- **Langfuse** — prompt registry and observability.
- **PostgreSQL** — LangGraph checkpoints and `app_db` tables (`users`, `auth_token_blacklist`, `conversations`, `messages`, `plans`).
- **Bailian / dashscope** — primary LLM and web-search provider.
- **Tavily** — fallback web-search provider.
- **Bailian models** — qwen-max, qwen-plus, qwen-turbo, qwen-long (+ optional deepseek-r1 for reasoning).

See `docs/adr/0002-self-hosted-infrastructure.md`.

## Policies

The operational rules below apply across all phases unless a phase overrides it. Per-phase overrides (e.g. P1 per-sub-query retry cap = 1) live in `docs/milestones.md`.

### Plan Section Count
A Plan must contain **1–8 Sections**. 0 Sections is rejected at validation; >8 prompts the user to consolidate before saving.

### Conversation Lifetime
A Conversation (with its Report, plan history, and LangGraph checkpoints) is retained in PostgreSQL for **30 days** after the last activity, then eligible for cleanup. Within 30 days, the user can resume a session via `GET /sessions/{id}/state` plus SSE reconnect using `Last-Event-ID`.

### Session Resume
The frontend can recover a session mid-flight: `GET /sessions/{id}/state` returns the current LangGraph checkpoint snapshot; SSE supports `Last-Event-ID`-based replay so a refreshing browser catches up without losing progress.

### Session Resume (multi-user)
The User identity comes from the JWT bearer on `/sessions*` calls; conversations are scoped by `user_id`, so multiple users and multiple tabs per user coexist without state collision. P1 does not enforce per-user rate limits.

### Error Handling
Two categories of failure mode are explicitly handled:

- **Upstream LLM refusal** — behavior depends on which stage the LLM is in:
  - *User-facing stages* (`plan_generate`, `draft_generate`, `outline_generate` — output reaches the user directly): the operation returns **`422 Unprocessable Entity`** to the client; the UI surfaces the LLM's reason and prompts the user to change the query.
  - *Internal stages* (`sub_query_generate`, `polish` — output is consumed by downstream stages): silently fall back to the per-call fallback defined in `docs/milestones.md`. The refusal is logged in Langfuse but **not surfaced** to the user.
- **Mid-research insufficient data** (a Section cannot gather enough quality sources despite retries):
  the affected Section is reported with an **`Insufficient data`** flag in the Write Layer; the rest of the Report continues normally and is delivered.

The frontend shows only "Searching…" during retries and progress events; failure details surface at delivery time, not mid-stream.
