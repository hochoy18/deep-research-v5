# Project Milestones

Capability-driven phasing. Each phase ships a complete, end-to-end **vertical slice** of all three layers (Plan / Research / Write). Phases **deepen**, not extend sideways.

Why vertical slice → `docs/adr/0001-vertical-slice-staging.md`.

---

## Phase 1 — Vertical Slice MVP (α)

**Goal**: Signup → login → query → approved plan → research → report, end-to-end runnable. Username + password auth. Tracing only (no eval scoring).

### Functional surface (per layer)

**Auth** (P1)
- `POST /auth/signup` body `{username, password}` → `{token, user_id}`
- `POST /auth/login` body `{username, password}` → `{token, user_id}`
- `POST /auth/logout` invalidates the bearer
- `GET  /auth/me` returns current user from bearer
- JWT bearer required on every `/sessions*` endpoint; missing/invalid → 401
- Password storage: **bcrypt** (industry standard, single dependency)
- **P1 explicitly does NOT include**: password reset, email verification, 2FA, OAuth, refresh tokens. (Production-grade auth replaces username + password in P3.)

**Plan Layer**
- LangGraph node `plan_generate(query) → StructuredPlan`
- LangGraph node `plan_wait_human(state) → interrupt` (resumes on Approve action)
- Langfuse prompt `plan_generate_system` (no model name in code — only in Langfuse prompt config)
- Structured Plan conforms to the **JSON Schema in `CONTEXT.md`** (`Plan` / `Section` / `Note` field-level types and bounds)
- Frontend page `/sessions/[id]/plan` renders Structured Plan editor
- Five HITL operations wired:
  - `POST /sessions/[id]/plan/edit` payload `{op: "edit" | "add" | "remove" | "note", section_id?, payload}`
  - `POST /sessions/[id]/plan/approve` triggers downstream
- Persist every plan revision as a new `plans` row; `plans.version` increments by 1 each time
- **Edit rule** (HITL concurrency): `Edit` / `Add` / `Remove` / `Note` are **rejected with HTTP 422** once `plan.approved == true`. Approve sets the latch; race resolves at HTTP order.
- **Note semantics**: Section-level Note text is injected into the Research layer's `sub_query_generate` prompt for that Section. P1 Note is per-Section only.

**Research Layer** (one subgraph per Section)
- `sub_query_generate(section) → [sub_query]`:
  - Uses `section.sub_questions` from Plan if provided; otherwise LLM produces 2–3
  - **Validation**: 1–5 items, each unique non-empty ≤200 chars
  - **Failure fallback**: invalid output retries up to **3 times**; on the 4th miss, the entire Section brief is used as the single sub-query
  - Includes the Section's `note.text` in the prompt
- `web_search(sub_query, top_k=4) → [Source]` (dashscope primary, tavily fallback on error)
- `merge_sources(sources)` → aggregated per Section
- **Global URL deduplication**: identical URLs across multiple sub-queries are merged into one Source for the Session (single citation in the Report)
- `eval_per_sub_query(section, sources) → pass | fail` (P1 retry cap = **1**, not 2)
- Langfuse prompts: `research_sub_query_generate_system`, `research_eval_per_sub_query_system`
- Concurrency: sections sequential; sub-queries within a section parallel (`asyncio.gather`)

**Write Layer**
- `outline_generate(plan, all_sources) → outline`
- `draft_generate(outline, all_sources) → draft_with_citations`
- `polish(draft) → final_report` — single pass
- Langfuse prompts: `write_outline_system`, `write_draft_system`, `write_polish_system`
- Output: markdown (`TL;DR` + sections + `[n]` inline citations + Sources Appendix)
- Default length 3–5 pages
- Citation numbering is **globally continuous** across the Report (not per-Section)

### Backend API surface

All `/sessions*` endpoints require a valid JWT bearer (missing/invalid → 401). Within `/auth/*`, only `signup` and `login` are public; `/auth/logout` and `/auth/me` require a valid bearer.

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/signup` | body `{username, password}` → `{token, user_id}` |
| POST | `/auth/login` | body `{username, password}` → `{token, user_id}` |
| POST | `/auth/logout` | invalidates bearer |
| GET  | `/auth/me` | current user from bearer |
| POST | `/sessions` | body `{query}` → `{session_id}` (authenticated) |
| GET  | `/sessions/{id}/events` | SSE stream; event types: `plan_ready` / `research_progress` / `report_ready` / `error`. **`research_progress` fires once per Section** (Section 1/N → 2/N → …), not per sub-query |
| POST | `/sessions/{id}/plan/edit` | apply HITL edit; returns updated plan; **422 if `plan.approved == true`** |
| POST | `/sessions/{id}/plan/approve` | approve plan; sets `plan.approved = true`; triggers research |
| GET  | `/sessions/{id}/report` | final markdown report (authenticated) |
| GET  | `/sessions/{id}/state` | current LangGraph state snapshot (authenticated) |

### Infra & deployment

- v5_frontend = Next.js (App Router) + TypeScript + `react-markdown` for report rendering
- v5_backend = FastAPI + Python 3.11+ + LangGraph + LangChain + bcrypt for password hashing
- PostgreSQL: one instance, two databases
  - `langgraph_checkpoints_db` — LangGraph-owned schemas
  - `app_db` — project tables (see schema below)
- Self-hosted Langfuse: prompt registry + traces only
- **P1 is single-tenant** — no multi-tenancy isolation concerns; `user_id` from the JWT scopes all queries

### Reusable seams (4 + 1; same across all phases)

- `call_llm(prompt_id, variables, *, model_override=None)` — every LLM call goes here
- `search_web(query, top_k=4, provider='dashscope')` — primary + tavily fallback
- `evaluate(rubric_name, text)` — both Research and Write call this
- `stream_event(event_type, payload)` — every UI event
- `extract_citations(text)` — Research and Write both need this; one function

No code outside these may touch an LLM provider, a search provider, an event channel, or a citation format.

### Database schema (`app_db`)

```sql
users (
  id            UUID PRIMARY KEY,
  username      TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at    TIMESTAMP NOT NULL DEFAULT now()
)

auth_token_blacklist (
  token_hash    TEXT PRIMARY KEY,    -- SHA-256 of the bearer token
  user_id       UUID REFERENCES users(id),
  expires_at    TIMESTAMP NOT NULL,  -- mirrored from the JWT 'exp' claim
  created_at    TIMESTAMP NOT NULL DEFAULT now()
)

conversations (
  id              UUID PRIMARY KEY,
  user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  query           TEXT NOT NULL,
  report_md       TEXT,
  created_at      TIMESTAMP NOT NULL DEFAULT now(),
  updated_at      TIMESTAMP NOT NULL DEFAULT now()
)

messages (
  id              UUID PRIMARY KEY,
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role            TEXT NOT NULL,    -- 'user' | 'system' | 'event'
  content         TEXT,
  event_type      TEXT,
  created_at      TIMESTAMP NOT NULL DEFAULT now()
)

plans (
  id              UUID PRIMARY KEY,
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  sections        JSONB NOT NULL,
  plan_note       TEXT,             -- Plan-level Note (P2+); NULL/empty in P1
  version         INT NOT NULL,
  approved        BOOLEAN NOT NULL DEFAULT false,
  approved_at     TIMESTAMP,
  created_at      TIMESTAMP NOT NULL DEFAULT now(),
  updated_at      TIMESTAMP NOT NULL DEFAULT now()    -- bumped on every revision
)
```

Issue #3 tightened four columns against this table: `messages.role`,
`conversations.user_id`, `plans.sections` and `plans.approved` are NOT
NULL (a Message has no meaning without a role, a Conversation has no owner
if `user_id` is nullable, and a Plan with no sections is not a Plan), and
the three foreign keys cascade. `app/db/models.py` and the Alembic
migrations are the authority; this table mirrors them.

### Langfuse prompt registry (P1)

Code references these by `prompt_id` only; model name lives in each prompt's config:

| prompt_id | used by |
|---|---|
| `plan_generate_system` | plan_generate |
| `research_sub_query_generate_system` | sub_query_generate |
| `research_eval_per_sub_query_system` | eval_per_sub_query |
| `write_outline_system` | outline_generate |
| `write_draft_system` | draft_generate |
| `write_polish_system` | polish |

### Acceptance criteria (P1 must satisfy all)

Functional — Auth:
- `POST /auth/signup` with new username/password → 201 with `{token, user_id}`; duplicate username → 409
- `POST /auth/login` with correct credentials → 200 with `{token, user_id}`; wrong password → 401
- `POST /auth/logout` → token blacklisted; subsequent `/sessions*` calls with the same bearer → 401 (verifiable: `auth_token_blacklist` row exists with `token_hash` matching the bearer and `expires_at` ≥ now)
- `GET /auth/me` returns current user from bearer; missing/invalid bearer → 401
- `/sessions*` without bearer returns 401

Functional — Plan / Research / Write:
- Single query → plan rendered in editor within ~5s
- All five HITL ops work end-to-end; `Edit` / `Add` / `Remove` / `Note` return 422 after `Approve`; calling `POST /sessions/{id}/plan/approve` a second time returns 200 idempotently (does not re-trigger research, does not 422)
- Approve triggers research; SSE events stream to UI; `research_progress` fires **once per Section**
- Dashscope failure (mocked) → Tavily kicks in
- Final report renders, with `[n]` citations resolving to Sources Appendix; **numbering globally continuous**
- Plan Section count bounded at **1 ≤ N ≤ 8**: 0 rejected, >8 prompts user to consolidate
- Plan field-level validation enforced (`title` 1–100, `brief` 1–500, `sub_questions` 0–5 each ≤200, `note.text` ≤1000)
- Sub-query generation: invalid output retries up to 3 times, then the entire Section brief is used as a single sub-query (verifiable by mocking failure)
- **Source URL dedup verified**: same URL from two sub-queries appears as a single Source in the Report
- Sub-query parallelism confirmed: 3 sub-queries in a section complete in ≈ max(query_time), not sum
- **Note injection**: Section Note text shown to influence generated sub-queries (manual diff ok)

Functional — Errors & Resume:
- **Upstream LLM refusal**:
  - *Plan / Draft / Outline (user-facing)* → backend returns 422 with the LLM's reason; UI prompts user to revise the query
  - *`sub_query_generate` / `polish` (internal)* → silent fallback per P1 spec (sub-query uses Section brief after 3 retries; polish skipped → `draft_with_citations` shipped). Refusal logged in Langfuse, not surfaced to the user
- **Section insufficient data**: that section is reported with an `Insufficient data` flag; rest of the report delivered normally (whole-report not failed)
- **Browser refresh / multi-tab**: `GET /sessions/{id}/state` returns the current LangGraph checkpoint; SSE supports `Last-Event-ID`-based reconnect so a refreshing browser catches up
- **Data retention**: a conversation (with its checkpoints and Report) remains queryable for **30 days** from last activity

Observability:
- Langfuse shows a single session trace, with one span per LangGraph node
- All LLM calls tagged with their `prompt_id`
- All web-search calls recorded with provider (`dashscope` | `tavily`) on the span

Deliverables:
- v5_frontend builds, runs, completes signup → login → query → report in browser
- v5_backend builds, runs, all 10 endpoints work (4 auth + 6 session)
- PostgreSQL migrations apply cleanly (`alembic` or equivalent)
- Langfuse prompts registered (so they're versionable)
- Demo script: `docs/demo/p1.md` — exact steps from clean checkout to a finished report

### Out of scope (P1)

- ❌ Whole-plan coverage evaluation
- ❌ 2-retry cap on per-sub-query eval (P1 = 1)
- ❌ Multi-pass write polish (P1 = 1)
- ❌ Langfuse scoring / quality judging
- ❌ Password reset, email verification, 2FA, OAuth, refresh tokens (P1 auth = username + password + JWT only)
- ❌ Conversation history UI (P1 stores; doesn't list)
- ❌ Cancel mid-research
- ❌ Sub-query hard caps (P1 uses soft placeholder; P2 uses P1 telemetry to set real caps)
- ❌ Per-sub-query granular progress events (P1 = per-Section)
- ❌ Plan-level Note (P1 Note is per-Section only)

### Sub-query placeholder behaviour for P1

Same as before; placeholder, defer to P2 with P1 telemetry.

1. **User sub_questions are honored** — every one written in HITL is used (not filtered)
2. **Empty → LLM fills to soft target 2–3** via prompt guidance (no enforcement)
3. **Execution order** — sections sequential; sub-queries within a section parallel
4. **No hard caps** — observe and measure during P1

---

## Phase 2 — Depth + Eval Scoring + History View

**Goal**: Tighten eval, lift write polish, lock in sub-query rules, surface conversation history. Auth was already shipped in P1 (this phase deepens other things).

### Per-layer deepening

**Plan Layer**
- Optional LangGraph node `plan_suggested_edits(plan, query) → delta_suggestions` (not on critical path)
- Store every plan revision as a new row in `plans` with bumped `version`
- **Plan-level Note** is now supported alongside Section-level Note (Plan-level Note applies to all Sections)
- Diff/visualization UI deferred to P3 (P2 stores, doesn't expose)

**Research Layer**
- New node `eval_whole_plan(all_section_sources) → coverage_report` (runs after all Sections finish)
- Coverage rule: every Plan Section must have ≥1 source with `authority_score >= 0.5`
- Auto-fill: if a Section is under-covered, generate 1–2 additional sub-queries and search (one pass, no retry)
- Eval retry cap: **1 → 2**
- New rubric items in evaluation:
  - source authority (domain heuristic — `.edu`, `.gov`, known outlets weighted higher)
  - claim-level conflict detection (LLM judge: do two sources disagree?)
- **Sub-query rules locked in** using P1 telemetry:
  - session cap (e.g. ≤ 20)
  - section cap (e.g. ≤ 5)
  - trust level (confirm "use user's, supplement to N" if P1 data shows user inputs are high-quality)
- Tavily fallback rate dashboarded in Langfuse (P1 just logs; P2 surfaces it)

**Write Layer**
- Polish loop: 1 → **2 passes** (`polish_2x(draft)`)
- New audit node `audit_citations(report, sources)` runs before delivery
  - verifies every `[n]` in report text maps to an entry in Sources Appendix
  - if any unresolved, regenerates the affected paragraph and re-audits
- Citation consistency enforced at delivery time

### Conversation History view

- New endpoint: `GET /conversations` — list user's past conversations (title from initial query, timestamp, last activity)
- Frontend profile page renders the list; clicking a row opens `/sessions/{id}/state` and resumes the session
- If the conversation is finished, fetch `GET /sessions/{id}/report` directly
- Conversations beyond the 30-day retention window return 410 Gone

### Observability

- Langfuse scoring: register `eval_judge_quality` prompt and run on finished reports
- Trace spans show: per-section eval pass/fail, final judge score (1–5), retry counts
- Langfuse dashboard queries pre-built:
  - pass-rate over time
  - retry rate per `prompt_id`
  - fallback rate (`dashscope` vs `tavily`)
  - avg sources/section distribution

### Acceptance criteria (P2)

- Whole-plan eval runs and auto-fills under-covered Sections
- Per-sub-query eval retries up to 2 times now
- Polish runs 2 passes; citation audit catches inconsistencies before delivery
- Sub-query rules documented in `docs/research_rules.md` and locked into code
- P1 demo can be reproduced end-to-end
- Langfuse dashboards render
- Conversation history list viewable; clicking a finished conversation opens its stored Report

### Out of scope (P2 → P3)

- Cancel mid-research
- Plan version diff UI
- Hallucination guardrail
- Production auth (OAuth replacing username + password)
- Rate limiting
- Multi-language UI

---

## Phase 3 — Production Polish

**Goal**: Robustness, observability, and the foundation for going to production.

### Research hardening

- Source authority heuristic refined to a scoring formula:
  - `domain_class` (e.g. academic / news / blog / unknown) + `citation_count_proxy` (presence in known indexes) → `authority_score`
- Claim-level conflict detection: LLM extracts key claims per source, surfaces disagreements as `conflicts.json` attached to the report
- Vector cache:
  - add `pgvector` extension
  - cache embeddings of past `Source.text` keyed by normalized query
  - before any new search, look up cached sources first; if coverage ≥ threshold, skip the call
- **Cancellation**: `POST /sessions/{id}/cancel` flips a flag; LangGraph checks at every node boundary; partial state is rolled back via checkpoint revert

### Write hardening

- New pipeline: `outline → draft → fact_check → polish → final`
- `fact_check`:
  - each `[n]` referenced in the prose must be supported by Source[n]'s content
  - unsupported references trigger paragraph regeneration; loop up to 2 times, then drop the unsupported citation and add a `flag` marker
- Hallucination judge (`eval_judge_hallucination`): sentence-level scoring; if score > threshold, regenerate that sentence

### Plan hardening

- Query intent classification (`plan_classify_intent`): output `{intent ∈ academic | commercial | technical | other}` with confidence
- Plan templates stored as `backend/app/plan_templates/{intent}.yaml`:
  ```yaml
  academic:
    default_sections: [background, prior_work, methodology, results, open_questions]
    typical_lens: peer_reviewed_first
  ```
- High-confidence matches use templates; otherwise full LLM generation
- User can opt out ("don't use templates") via a Plan editor toggle

### Infra

- **Production auth: OAuth replaces username + password from P1**. Migration path: existing users re-login once via OAuth provider; no password reset needed.
- Rate limit: per-user, per-hour; returns 429 with `Retry-After`
- Monitoring beyond Langfuse:
  - p50 / p95 latency per layer (Plan / Research / Write)
  - eval pass rate trend
  - fallback rate trend
  - error budget burndown
- Multi-language UI: i18n setup; English + Chinese minimum at P3 launch
- Sentry (or equivalent) error capture; OpenTelemetry traces layered on LangGraph spans

### Acceptance criteria (P3)

- 100% of eval signals (per-sub-query, whole-plan, final judge) are queryable in Langfuse
- Cancel-mid-research correctly stops within one node boundary; no orphan checkpoints
- Common-intent queries (≥80% of test set) hit cached templates → faster plan generation observed in metrics
- Hallucination rate (judge) below configured threshold (e.g. < 5%)
- OAuth login works; rate limit triggers under load test
- Latency dashboards live and report daily

### Out of scope (P3 → future)

- Mobile app
- Other LLM providers (Anthropic / OpenAI / others)
- Public API
- Team workspace / collaboration
- User-supplied source ingestion (PDF, URL)

---

## Phase 4+ — Beyond P3 (placeholder)

Decide after P3 lands. Likely candidates ordered by expected value:

1. **User-supplied sources** — user uploads PDFs / pastes URLs to ground research on their own documents; adds ingestion + chunking
2. **Long-running async research** — kick off a research, leave it running for hours; notify on completion (email / webhook)
3. **Other LLM providers** — generalize the model-routing seam for Anthropic, OpenAI, others
4. **Team workspace** — shared sessions, comments on plans
5. **Mobile app / PWA** — read-only / dashboard on the go

---

## Cross-phase constants

These apply across **every** phase and don't change between phases:

- **Module boundaries** — each of the three layers (Plan, Research, Write) lives in its own sub-package; cross-layer imports are forbidden. Cross-layer coordination goes only through the LangGraph state seam and the public seams listed below (4 + 1). See `docs/adr/0003-function-consolidation.md`.
- **Four seams + 1**: `call_llm`, `search_web`, `evaluate`, `stream_event`, `extract_citations` — single source of truth for each surface
- **Langfuse Prompt is the source of truth** for per-prompt model selection; code references `prompt_id` only. See `docs/adr/0004-langfuse-prompt-as-model-routing.md`.
- **One PostgreSQL instance, two databases**: `langgraph_checkpoints_db` (LangGraph-owned) + `app_db` (project-owned)
- **Eleven endpoints in P2** (P1: 4 auth + 6 session; P2 adds `GET /conversations` → 7 session). P3 adds `POST /sessions/{id}/cancel` (12 total).
- **Concurrency model**: sections sequential, sub-queries within section parallel — this stays for every phase
- **Bailian / dashscope primary** LLM and web-search provider; tavily as web-search fallback
- **Citation numbering**: globally continuous across the Report, never per-section

---

## Tracking

- Per-phase tickets live on the issue tracker (GitHub issues via `gh` CLI; see `docs/agents/issue-tracker.md`)
- Each phase is a tracer-bullet: implement blocker tickets first, demo at the seam, then deepen
- P1 is the only phase with hard "all of this must work" acceptance today; P2/P3 acceptance evolves with design
