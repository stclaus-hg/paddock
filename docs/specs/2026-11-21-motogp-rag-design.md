# Paddock — MotoGP RAG — Design

> *Paddock — ask anything about MotoGP riders.*

Date: 2026-11-21
Status: approved by owner (2026-11-23)

## 1. Intent and why

A pet project with two goals, in this order:

1. **Learn how RAG works from the inside.** Every stage — fetching data, chunking,
   embeddings, vector search, routing, prompting — is written by hand so the owner
   sees what each part does. Frameworks that hide these stages are deliberately avoided.
2. **Portfolio piece.** What should make it stand out is not the UI but *measured quality*:
   a golden question set, an evaluation harness, and README tables showing how each
   design change moved the numbers.

Domain: **MotoGP**, chosen because the owner follows it closely and can judge whether an
answer is correct — which is what makes writing the golden set possible.

The domain naturally forces a **hybrid** system, which is the main engineering story:

- **Rider biographies** (how they started, which classes and teams they went through)
  are free text → classic vector retrieval works.
- **Statistics** (wins, poles, podiums, retirements, "dominance") are numbers in tables →
  vector retrieval fails at counting and aggregation; these go through SQL.
- Mixed questions ("Which was Márquez's best season, and why did he leave that team?")
  need both.

The README narrative this enables: "naive RAG gets statistics wrong N% of the time;
routing stats questions to SQL brings it to M%".

## 2. Goals (V1)

- Answer biography questions about MotoGP premier-class riders, grounded in retrieved text,
  with source links.
- Answer statistics questions by generating and running SQL against structured results,
  never from the LLM's own memory.
- Answer mixed questions by combining both paths.
- Route each question automatically (bio / stats / mixed / out of scope).
- Evaluate every stage against a golden set and report the numbers.
- Run the LLM locally first (Ollama), switchable to a hosted API by one config setting,
  and compare both on the golden set.
- Expose it through a FastAPI backend and a thin React chat UI.

## 3. Non-goals (V1)

- **Technical content** — bikes, engines, tyres, electronics, regulations. Planned as V2,
  added once the core works ("added a new source, here is how quality changed").
- Moto2 / Moto3 / 500cc as structured data. Lower-class careers appear only as biography text.
- Per-race crash data ("did he crash at Mugello 2019?") — not available as open data.
- Live or current-weekend data, auth, multi-user, cloud deployment, fine-tuning.
- Polished frontend. React is not the owner's strong side; the UI stays minimal.

## 4. Anti-goals (failure even if it "works")

- Numbers in answers that did not come from a SQL result or a cited retrieved passage.
  *[Claude's call:]* statistics within the structured scope (premier class, 2002+) always come from
  SQL. A number quoted verbatim from a retrieved biography passage (a 125cc title, a birth year) may
  appear with its citation. When a question reaches past the data (e.g. Rossi's titles, one of which
  was won in 500cc in 2001), the answer gives the in-scope figure and states the data boundary
  ("6 in the MotoGP era, 2002+; earlier seasons are not in the data").
- Calling a retirement ("Ret") a crash. Results tables do not say why a rider retired.
- A framework (LangChain, LlamaIndex, …) doing retrieval, routing, or prompting in the core.
  It may appear later only as a separate comparison baseline.
- A demo without measured quality — no eval numbers means the portfolio goal is missed.

## 5. Scope of data

- **Class:** MotoGP premier class only.
- **Seasons:** 2002 (start of the four-stroke MotoGP era) through the most recent completed season.
- **Riders:** everyone with at least one premier-class start in that range.
- **Source:** English Wikipedia — rider articles (biographies), season articles,
  Grand Prix articles (race classification and starting grid). Wikipedia text is CC BY-SA:
  answers and README attribute it.
- **Crash totals (stretch goal, V1):** Dorna publishes per-rider season crash totals in yearly
  articles on motogp.com. If included, they are transcribed into a small hand-curated CSV for the
  seasons where they exist, with source URLs, and treated as the only source of "crash" numbers.
- The repository contains the ingestion code, not the downloaded data (data is fetched by a
  command). *[Claude's call: keeps the repo small and avoids redistributing third-party pages.]*
- **Pinned snapshot.** *[Claude's call:]* ingestion fetches each page at a fixed Wikipedia revision.
  A small manifest (page title → revision id, plus the snapshot date) is committed, so a re-fetch
  reproduces the same data and the golden set and README numbers stay valid. The 2026 season is
  included only if its articles are complete at snapshot time; the manifest records the last season.

## 6. Statistics: what "dominance" means

The owner's definition: an effective rider dominates every race and every qualifying.
Translated into metrics, per rider, overall and per season:

| Area | Metric |
|------|--------|
| Races | win rate (wins / starts), podium rate, average finishing position (classified finishes only) |
| Qualifying | pole rate (grid position 1 / starts), average grid position |
| Reliability | finish rate (classified finishes / starts) |

Rules:

- **Minimum 10 starts** for rate-based rankings, so a one-off replacement rider with one
  podium does not rank above Rossi. *[Claude's call; threshold is a constant, easy to change.]*
- **Sprint races (2023+) are stored and counted separately** from main races.
- Pole position is taken as grid position 1 in the Grand Prix starting grid.

## 7. Approaches considered

| Approach | Trade-off | Decision |
|----------|-----------|----------|
| **A. By hand on Postgres + pgvector** | One database holds both vectors and stats tables, so stats results and text chunks share rider/season keys and retrieval can be filtered by what SQL found. More code to write, but every stage is visible. Familiar tools (Python, Postgres). | **Chosen** |
| B. Framework (LlamaIndex) | Router and text-to-SQL come built in; prototype in an evening. Hides exactly what the owner wants to learn. | Rejected for the core; possible later as a comparison baseline |
| C. Fully local, local-only forever | Free and private, but no GPU: slow generation and weaker SQL from small models, hurting the stats half most. | Rejected as the final state; adopted as the *starting* LLM (see below) |

**Owner's decision:** approach A, with the LLM running **locally via Ollama first**, behind an
interface that allows switching to a hosted API (e.g. Claude) with one config setting.

## 8. The how — decided parts

### 8.1 Stack

- Python, FastAPI backend, thin React chat frontend.
- PostgreSQL with the `pgvector` extension, run via docker-compose.
- Embeddings: a local sentence-transformers model on CPU (no GPU on the dev machine).
- LLM: Ollama with a small model (3–8B parameters; machine has 23 GB RAM, no GPU).
  Hosted API implementation added later.
- No RAG/LLM frameworks in the core. Plain libraries only (DB driver, HTTP client,
  sentence-transformers, FastAPI).

### 8.2 Components

1. **Ingestion** — fetches Wikipedia pages for seasons, Grand Prix events and riders; parses
   results tables into structured rows and biography text into sections.
2. **Structured store** — tables for riders, seasons, events, results (race and sprint as a
   session type; finishing position or status; points; grid position) and a
   **rider-season link** (rider, season, team, constructor/bike). The link table serves both
   stats and biographies, and later V2 technical content. Dominance metrics are SQL views.
3. **Text store** — biography sections chunked, embedded, stored in pgvector with metadata
   (rider id, article section, source URL).
4. **Retriever** — embeds the question, returns top-k chunks, optionally filtered by rider.
5. **Text-to-SQL** — LLM gets a schema description and the question, writes a SELECT; the query
   runs under a read-only DB role with a timeout and row limit; non-SELECT statements are rejected.
6. **Router** — LLM classifies the question as `bio` / `stats` / `mixed` / `out_of_scope`.
   *[Claude's call on both points below.]*
   - `out_of_scope` covers V2 technical topics, lower-class statistics, per-race crashes and
     anything non-MotoGP; the system declines and says what it does cover.
   - `mixed` is **sequential**: the stats part runs first (SQL), its result yields entities
     (rider, season, team), and biography retrieval is then filtered by them. Example: "best season
     of Márquez and why he left that team" → SQL finds season + team → retrieval for that rider,
     filtered to chunks about that team/period → answer from both. This requires chunk metadata
     beyond rider id: the years and team(s) a section covers, where derivable.
7. **Answer generator** — writes the final answer from the provided context only, citing
   Wikipedia URLs and/or showing the SQL used.
8. **LLMClient interface** — one method (prompt in, text out, plus a structured-output helper);
   implementations: Ollama (first), hosted API (later). Selected by config.
9. **Evaluation harness** — CLI command that runs the golden set and prints/saves result tables.
10. **API + UI** — FastAPI endpoint for questions; React chat that shows the answer, its sources,
    and the SQL when one was run.

### 8.3 Evaluation

- **Golden set**, roughly 30–50 questions across the four types. For each: the question, its type,
  and the expected answer; for bio questions the article(s)/section(s) that contain it; for stats
  questions the expected result (reference SQL optional). Stored as a YAML/JSON file in the repo.
  *[Claude's call on the workflow:]* it is built per stage, right before that stage needs it —
  bio questions before retrieval eval, stats questions once the schema exists. Claude drafts
  candidates from the snapshot; the owner, as domain expert, corrects, removes, and adds his own.
  The set is bound to the pinned snapshot.
- **Grading final answers:** an LLM-as-judge in V1 compares each answer to the expected answer;
  the owner spot-checks a sample to confirm the judge agrees with him. *[Claude's call: manual
  grading of 30–50 answers after every change would not be sustained.]*
- Metrics:
  - routing accuracy;
  - retrieval: recall@k (did the right article/section come back);
  - text-to-SQL: execution accuracy (result set matches the reference result);
  - final answer correctness (LLM-as-judge, spot-checked by the owner).
- The same set is run on the local model and the API model; the comparison table goes in the README.
- Every notable change (chunking strategy, embedding model, k, prompt) is measured before/after.

### 8.4 Who writes what

**Owner's decision:** split by learning value, with a fallback to "Claude writes everything,
owner reads and studies it" if the pace becomes a problem.

| Claude writes (plumbing) | Owner writes, guided (RAG core) |
|--------------------------|----------------------------------|
| Wikipedia ingestion and table parsing, snapshot manifest | Chunking |
| DB schema, docker-compose, project setup, tooling | Embedding + storing vectors |
| Stats SQL views | Retriever (vector search, metadata filters) |
| FastAPI layer, React chat | Text-to-SQL prompt + safety checks |
| Hosted-API `LLMClient` implementation | Router, mixed-question flow, answer prompt |
| | Ollama `LLMClient`, evaluation harness and metrics |

For owner-written parts, the plan is a sequence of **small teaching steps**: Claude explains the
idea in plain language, provides failing tests (or writes them together with the owner), the owner
implements, Claude reviews. One step at a time; the plan has explicit stop points between steps.
Claude's parts are ordinary implementation tasks, done with TDD as well.

### 8.5 Build order

1. Ingestion + structured tables.
2. Biography retrieval + retrieval eval (no LLM needed yet).
3. Stats SQL views + text-to-SQL + SQL eval.
4. Router + mixed answers + end-to-end eval.
5. FastAPI.
6. React chat.
7. Hosted API LLM + local-vs-API comparison.

V2 afterwards: technical content (engine eras, tyre suppliers, electronics, aero, bikes).

## 9. Constraints

- Dev machine: Linux, 8 CPU cores, 23 GB RAM, **no GPU**. Free RAM grows once the owner
  closes browser tabs; a 7–8B quantized model should fit.
- System Python is 3.8; the project uses a modern Python managed by `uv` (already installed).
  *[Claude's call.]*
- Wikipedia requests use a generic User-Agent and respect rate limits.
- The owner practises TDD with pytest; tests are expected.

### 9.1 Code conventions

Adopted from the owner's day-job Python conventions so the project feels familiar.
*[Claude's call: only the generic parts; the work project's domain rules do not apply.]*

- Python 3.14 (fall back to 3.13 only if a key dependency has no wheels), `uv` for env and lockfile.
- Ruff for lint + format, line length 120; rule set along the lines of
  `E, W, F, I, N, UP, B, S, T20, SIM, RUF, PL, PT, DTZ`.
- Full type annotations, mypy strict on production code (not on tests). `T | None`, `list[str]`,
  no `from __future__ import annotations`.
- `httpx` for HTTP (not `requests`), `structlog` for logging.
- No magic numbers/strings with domain meaning: named constants with a short comment;
  `StrEnum` for finite sets (question type, session type, result status).
- TDD: red → green → refactor; tests fail on assertions, not on import errors.
- Comments only for a non-obvious *why*.

## 10. Left to the builder

- Which embedding model and which Ollama model (within the constraints above).
- Chunking strategy and k — these are meant to be experimented with and measured.
- How Wikipedia is fetched and parsed (MediaWiki API vs HTML), and how table edge cases
  (shared rides, substitutes, cancelled races, half points) are normalised.
- Exact table columns, prompt wording, project layout.
- Question language: English for V1, matching the source data. *[Claude's call.]*
