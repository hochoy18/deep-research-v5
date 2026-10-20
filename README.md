# deep-research-v5

3-layer deep-research agent (Plan / Research / Write), shipped in vertical-slice milestones. Current phase: **P1 (Vertical Slice MVP, α)**.

- Vocabulary & glossary: [`CONTEXT.md`](./CONTEXT.md)
- Phase plan (EN): [`docs/milestones.md`](./docs/milestones.md)
- Phase plan (中文): [`docs/milestones.zh-CN.md`](./docs/milestones.zh-CN.md)
- Architectural decisions: [`docs/adr/`](./docs/adr/)
- Agent skills / issue-tracker conventions: [`CLAUDE.md`](./CLAUDE.md), [`docs/agents/`](./docs/agents/)

## Running locally

Prerequisites: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node 18.18+
(Next.js 15's floor), and a PostgreSQL instance reachable at `DATABASE_URL`.

### Database

ADR 0002 puts both databases on one instance. This project owns `app_db` today;
`langgraph_checkpoints_db` arrives with the Postgres checkpointer (issue #9).
Keep these values in sync with `DATABASE_URL` in `backend/.env`:

```bash
DB_USER=postgres
DB_PASSWORD=change-me

docker run -d --name pg15 --restart unless-stopped \
  -e POSTGRES_USER="$DB_USER" -e POSTGRES_PASSWORD="$DB_PASSWORD" \
  -p 5432:5432 postgres:15-alpine
docker exec pg15 createdb -U "$DB_USER" app_db
```

### Backend — `:8000`

```bash
cd backend
cp .env.example .env    # first run only: edit DATABASE_URL, JWT_SECRET, CORS_ORIGINS
uv sync                 # first run only
uv run --env-file .env alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

`uvicorn` picks up `backend/.env` on its own — `app/main.py` calls
`load_dotenv()` before building the app. Alembic does not: `migrations/env.py`
calls `get_settings()` against the raw environment, so it fails with
`DATABASE_URL is required` unless you pass `--env-file`.

Generate a JWT secret with:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

### Frontend — `:3000`

```bash
cd frontend
cp .env.example .env.local    # first run only
npm install                   # first run only
npm run dev
```

The browser calls the backend directly at `NEXT_PUBLIC_API_BASE` — there is no
Next.js proxy (`frontend/next.config.mjs`). So the backend's `CORS_ORIGINS`
must list `http://localhost:3000`, or every browser request is rejected before
it reaches a route. `TestClient` does not enforce this, which is why a green
backend suite can still pair with a blank page.

### Tests

```bash
cd backend  && uv run pytest     # 172 passed
cd frontend && npm test          # 44 passed
```

Each suite must run from its own directory. `backend/pyproject.toml` sets
`pythonpath = ["."]`, so `uv run pytest` from the repo root collects the tests
but cannot import `app`.

### Running without a model

Plan generation reaches a real model by default (`LLM_PROVIDER=dashscope`).
Set `LLM_PROVIDER=stub` in `backend/.env` to get a deterministic in-repo Plan
and no network calls — the vertical slice then runs fully offline.
