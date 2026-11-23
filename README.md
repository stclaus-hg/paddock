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

Database tests are marked `db`; without Docker run `uv run pytest -m "not db"`.

## Building the knowledge base

The data is a pinned snapshot of the English Wikipedia: MotoGP (premier class) race and sprint results from
2002 to the last completed season, plus the articles of every rider who started a race.

```bash
uv run paddock ingest fetch   # download the pages pinned in snapshot/manifest.json into data/raw/ (gitignored)
uv run paddock ingest load    # rebuild Postgres from the manifest and the cached pages
```

How ingestion works:

1. **snapshot** — `uv run paddock ingest snapshot` walks the season articles, follows each season's "Report"
   links to the Grand Prix articles and from their classification tables to the rider articles. Every page is
   pinned to its current revision id and cached; redirects (e.g. `Marc Marquez` → `Marc Márquez`) are recorded
   as rider aliases. The manifest is written only if the whole run succeeds. A past season with a Grand Prix
   lacking a MotoGP race table stops the run with the page named, except for races known to be cancelled; the
   current season is left out until it is complete. Only maintainers run this, to move the snapshot forward.
2. **fetch** — re-downloads exactly the pinned revisions, so anyone gets the same pages.
3. **load** — parses the cached pages and replaces the database contents in one transaction: `seasons`,
   `events`, `riders`, `results` (race and sprint, with `RET`, `DNS`, … kept as statuses — a retirement is
   never assumed to be a crash) and `bio_sections` (article sections with year and team metadata).

The full snapshot is ~600 pages; Wikipedia rate-limits anonymous clients, so a fresh `snapshot` or `fetch`
takes a while. Requests are serial, with a pause between them and retries on HTTP 429/5xx.

### Data attribution

Text and data come from the [English Wikipedia](https://en.wikipedia.org) and are licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Every stored page keeps its revision id; the
source of a biography section is `https://en.wikipedia.org/w/index.php?oldid=<revid>`.

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
