# Paddock

> Ask anything about MotoGP riders.

A hand-built hybrid RAG learning project: rider biographies are answered by vector retrieval,
statistics by text-to-SQL, mixed questions by both. See the design in
[`docs/specs/2026-11-21-motogp-rag-design.md`](docs/specs/2026-11-21-motogp-rag-design.md).

## Development setup

Prerequisites: [uv](https://docs.astral.sh/uv/), Docker.

```bash
uv sync                    # Python 3.14 env with all dependencies
docker compose up -d db    # Postgres 17 + pgvector on localhost:5434
uv run pytest              # tests
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

## Running the app

Prerequisites: uv, Node 22 (`frontend/.nvmrc`; with nvm run `nvm use` inside `frontend/`), Docker.

```bash
# terminal 1 — API on http://localhost:8000
uv run uvicorn paddock.api.app:app --reload --port 8000

# terminal 2 — chat UI on http://localhost:5173 (proxies /api to the API)
cd frontend && npm install && npm run dev
```

Frontend checks: `cd frontend && npm test && npm run lint && npm run build`.

> The RAG core is not connected yet: every question gets a placeholder answer.
> The response contract — `answer`, `question_type`, `sources`, `sql` — is already final.
