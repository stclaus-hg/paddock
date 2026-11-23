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
