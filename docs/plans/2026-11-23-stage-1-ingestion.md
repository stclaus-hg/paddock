# Stage 1 — Project Setup, Wikipedia Ingestion, Structured Store — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reproducible pipeline that snapshots English Wikipedia (MotoGP premier class, 2002 → last
completed season), caches the pages, and loads race/sprint results and rider biography sections into Postgres.

**Architecture:** Three CLI steps. `snapshot` discovers pages (season → Grand Prix → rider), pins each to a
Wikipedia revision id, caches its HTML and writes a committed manifest. `fetch` re-downloads any manifest
page missing from the cache (the reproducibility path). `load` parses the cached HTML and rebuilds the
database from scratch in one transaction. Parsers are pure functions over HTML strings and are tested on
real pages saved as fixtures.

**Tech Stack:** Python 3.14, uv, httpx, beautifulsoup4 + lxml, psycopg 3, structlog, pytest, ruff, mypy
(strict), PostgreSQL 17 + pgvector (docker-compose).

**Spec:** `docs/specs/2026-11-21-motogp-rag-design.md` (§5 data scope, §6 statistics rules, §8.2 components 1–2,
§8.4 — this stage is entirely "Claude writes", §9.1 conventions).

**Branch:** `stage-1-ingestion`, merged to `main` when Task 8 passes.

## Global Constraints

- Python 3.14 (3.13 only if a dependency lacks wheels); `uv` for env and lockfile.
- Ruff lint + format, line length 120, rules `E, W, F, I, N, UP, B, S, T20, SIM, RUF, PL, PT, DTZ`
  (tests ignore `S101, PLR2004`).
- mypy strict on `src/`, not on `tests/`. `T | None`, builtin generics, no `from __future__ import annotations`.
- `httpx` (never `requests`), `structlog` (never stdlib `logging` directly).
- No magic numbers/strings with domain meaning: named constants with a `#:` comment; `StrEnum` for finite sets.
- Comments only for a non-obvious why.
- Data scope: premier class only; seasons from **2002**; Wikipedia revisions pinned; downloaded HTML is
  **not** committed (`data/` is gitignored), the manifest **is** committed.
- Wikipedia requests: User-Agent `paddock/0.1 (learning project)`, serial requests, a pause between them.
- A retirement is stored as status `RET`, never as a crash. Sprint results are stored with session `sprint`,
  separate from `race`.

## Review Focus

1. **The same rider linked under two titles** (a redirect, e.g. an old name) must become one rider, not two.
   Test in Task 6 (`test_snapshot_maps_redirected_rider_links_to_one_canonical_title`) and Task 7
   (`test_load_merges_aliased_rider_links`).
2. **A rider without a Wikipedia article** (red link or plain text) must still have results, and no bio.
   Test in Task 3 (`test_red_link_rider_has_title_but_no_article`) and Task 7 (`test_rider_without_article_is_loaded`).
3. **Footnote markers inside numeric cells** (`"25[a]"`, `"1[note 2]"`) must not break or skew numbers.
   Test in Task 3 (`test_footnote_markers_are_stripped_from_numbers`).
4. **Network errors mid-snapshot** (HTTP 429/503) must be retried; a snapshot that ultimately fails must not
   leave a half-written manifest. Tests in Task 2 (`test_retries_on_503_then_succeeds`) and Task 8
   (`test_snapshot_command_writes_manifest_only_on_success`).
5. **A past season with a Grand Prix page lacking a MotoGP race table** must fail loudly and name the page,
   not silently drop the season. Only the current/future season may be excluded as incomplete.
   Test in Task 6 (`test_incomplete_past_season_raises_with_page_title`).

---

## File Structure

```
paddock/
  pyproject.toml                 # deps, scripts, ruff/mypy/pytest config
  .python-version                # 3.14
  .gitignore                     # .venv, data/, caches
  docker-compose.yml             # db: pgvector/pgvector:pg17 on host port 5434
  docker/init-test-db.sql        # creates paddock_test database
  README.md                      # setup + ingestion commands
  snapshot/manifest.json         # committed pinned snapshot (Task 8)
  scripts/fetch_fixture.py       # downloads a fixture page by revid (dev tool)
  src/paddock/
    __init__.py
    config.py                    # Settings from env
    logging.py                   # structlog configuration
    cli.py                       # `paddock ingest snapshot|fetch|load`
    models.py                    # enums + frozen dataclasses shared by parsers/loader
    ingest/
      __init__.py
      wiki_client.py             # MediaWiki API client (revisions, parse by revid, retries)
      cache.py                   # HTML cache keyed by revid
      html_utils.py              # shared cell-text / link helpers
      race_parser.py             # GP page -> MotoGP race + sprint ResultRows
      season_parser.py           # season page -> EventRefs; season title rule
      bio_parser.py              # rider page -> BioSections with year/team metadata
      manifest.py                # Manifest (de)serialisation, atomic write
      snapshot.py                # discovery + pinning + completeness rule; ensure_cached
    db/
      __init__.py
      schema.sql                 # tables + rider_seasons view
      connection.py              # connect(), apply_schema()
      loader.py                  # load_snapshot(): rebuild DB from manifest + cache
  tests/
    conftest.py                  # fixture paths, db fixtures
    fixtures/wiki/README.md      # attribution (CC BY-SA), titles + revids
    fixtures/wiki/<revid>.html   # 5 real pages (Task 2)
    ingest/test_wiki_client.py
    ingest/test_race_parser.py
    ingest/test_season_parser.py
    ingest/test_bio_parser.py
    ingest/test_snapshot.py
    db/test_loader.py
```

---

### Task 1: Project scaffold and tooling

**Files:**
- Create: `pyproject.toml`, `.python-version`, `.gitignore`, `docker-compose.yml`, `docker/init-test-db.sql`,
  `README.md`, `src/paddock/__init__.py`, `src/paddock/config.py`, `src/paddock/logging.py`, `tests/conftest.py`,
  `tests/test_smoke.py`

**Interfaces:**
- Produces: `paddock.config.Settings` (frozen dataclass) with `database_url: str`, `test_database_url: str`,
  `cache_dir: Path`, `manifest_path: Path`; `paddock.config.load_settings() -> Settings` reading
  `PADDOCK_DATABASE_URL` (default `postgresql://paddock:paddock@localhost:5434/paddock`),
  `PADDOCK_TEST_DATABASE_URL` (default `.../paddock_test`), `PADDOCK_CACHE_DIR` (default `data/raw`),
  `PADDOCK_MANIFEST` (default `snapshot/manifest.json`).
- Produces: `paddock.logging.configure_logging() -> None`.
- Produces: pytest marker `db` (tests needing Postgres), registered in `pyproject.toml`.

- [ ] **Step 1: Create branch and project**

```bash
cd /home/quantum/dev/pet/paddock && git checkout -b stage-1-ingestion
uv python install 3.14
uv init --package --name paddock --python 3.14 .
uv add httpx beautifulsoup4 lxml "psycopg[binary]" structlog
uv add --dev pytest ruff mypy types-beautifulsoup4 lxml-stubs
```

If `psycopg-binary` or `lxml` has no 3.14 wheel, switch `.python-version` to 3.13 and note it in the commit message.

- [ ] **Step 2: Configure tools in `pyproject.toml`**

`[project.scripts] paddock = "paddock.cli:main"`; ruff per Global Constraints with
`per-file-ignores = {"tests/**" = ["S101", "PLR2004"], "scripts/**" = ["T20"]}`; `[tool.mypy] strict = true`,
`files = ["src"]`; `[tool.pytest.ini_options] markers = ["db: needs the Postgres from docker-compose"]`,
`testpaths = ["tests"]`.

- [ ] **Step 3: docker-compose**

Service `db`, image `pgvector/pgvector:pg17`, env `POSTGRES_USER/PASSWORD/DB = paddock`, port `5434:5432`
(5432 and 5433 are taken on the dev machine), named volume, healthcheck `pg_isready -U paddock`, and
`./docker/init-test-db.sql` mounted into `/docker-entrypoint-initdb.d/` containing `CREATE DATABASE paddock_test;`.

- [ ] **Step 4: Write the smoke test**

```python
# tests/test_smoke.py
from paddock.config import load_settings

def test_settings_have_defaults(monkeypatch):
    monkeypatch.delenv("PADDOCK_DATABASE_URL", raising=False)
    settings = load_settings()
    assert settings.database_url.endswith(":5434/paddock")
    assert settings.cache_dir.as_posix() == "data/raw"
```

- [ ] **Step 5: Implement `config.py` and `logging.py`, run everything**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: 1 passed; ruff and mypy report no issues.
Run: `docker compose up -d db && docker compose exec db psql -U paddock -c '\l'`
Expected: databases `paddock` and `paddock_test` listed.

- [ ] **Step 6: Commit**

`.gitignore` must include `.venv/`, `data/`, `__pycache__/`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`.

```bash
git add -A && git commit -m "chore: scaffold project, tooling and dev database"
```

---

### Task 2: Wikipedia client, HTML cache, test fixtures

**Files:**
- Create: `src/paddock/ingest/__init__.py`, `src/paddock/ingest/wiki_client.py`, `src/paddock/ingest/cache.py`,
  `scripts/fetch_fixture.py`, `tests/ingest/test_wiki_client.py`, `tests/fixtures/wiki/README.md`,
  `tests/fixtures/wiki/{1367354866,1377682352,1373574739,1386901932,1387261184}.html`

**Interfaces:**
- Produces:
  - `PageRevision` (frozen dataclass): `requested_title: str`, `canonical_title: str`, `revid: int | None`
    (`None` = page does not exist).
  - `class WikiClient` — `__init__(self, http: httpx.Client, request_interval_s: float = REQUEST_INTERVAL_S)`;
    `latest_revisions(self, titles: Sequence[str]) -> dict[str, PageRevision]` keyed by requested title,
    following normalisation and redirects, batching `MAX_TITLES_PER_QUERY = 50`;
    `fetch_html(self, revid: int) -> str` (the `parse.text` HTML of `action=parse&oldid=<revid>`).
  - `make_http_client() -> httpx.Client` with base URL `https://en.wikipedia.org/w/api.php`, User-Agent from
    Global Constraints, timeout `HTTP_TIMEOUT_S = 30`.
  - `class HtmlCache` — `__init__(self, root: Path)`; `get(self, revid: int) -> str | None`;
    `put(self, revid: int, html: str) -> None` (file `root/<revid>.html`); `has(self, revid: int) -> bool`.
  - `WikiRequestError(Exception)` raised after retries are exhausted.

- [ ] **Step 1: Write failing tests** (use `httpx.MockTransport`; `request_interval_s=0` in tests)

```python
def test_latest_revisions_follows_redirects_and_marks_missing(): ...
    # mock returns query.normalized, query.redirects {"from": "Dani Pedrosa (racer)", "to": "Dani Pedrosa"},
    # pages [{"title": "Dani Pedrosa", "revisions": [{"revid": 111}]}, {"title": "Nobody", "missing": True}]
    assert result["Dani Pedrosa (racer)"] == PageRevision("Dani Pedrosa (racer)", "Dani Pedrosa", 111)
    assert result["Nobody"].revid is None

def test_latest_revisions_batches_by_50_titles(): ...
    # 120 titles -> exactly 3 requests observed by the transport

def test_fetch_html_requests_parse_by_oldid():
    # assert request params contain action=parse, oldid=42, prop=text, formatversion=2
    assert client.fetch_html(42) == "<div>ok</div>"

def test_retries_on_503_then_succeeds():  # Review Focus 4
    # transport returns 503, 429, then 200 -> result returned, 3 requests made

def test_raises_after_max_retries():
    # transport always 503 -> WikiRequestError after MAX_ATTEMPTS = 4 requests

def test_cache_roundtrip(tmp_path):
    cache = HtmlCache(tmp_path)
    assert cache.get(7) is None
    cache.put(7, "<p>x</p>")
    assert cache.has(7) and cache.get(7) == "<p>x</p>"
```

- [ ] **Step 2: Run** `uv run pytest tests/ingest/test_wiki_client.py -q` — Expected: FAIL (ImportError avoided by
  creating empty stubs first; failures are assertion errors).

- [ ] **Step 3: Implement `wiki_client.py` and `cache.py`**

All requests send `format=json`, `formatversion=2`. Retry on HTTP 429 and 5xx and `httpx.TransportError`, with
exponential backoff `RETRY_BASE_DELAY_S = 1.0` (doubling), up to `MAX_ATTEMPTS = 4`; honour `Retry-After` when
present. Sleep `request_interval_s` (default `REQUEST_INTERVAL_S = 0.5`) between successful requests.

- [ ] **Step 4: Run tests** — Expected: PASS.

- [ ] **Step 5: Fetch fixtures**

`scripts/fetch_fixture.py <revid-or-title> [...]` — an integer argument is fetched by revid; a title is resolved
with `latest_revisions` first and its revid printed. Writes `tests/fixtures/wiki/<revid>.html`. Fetch the pages
below, write the README table, and define one named constant per fixture in `tests/conftest.py`
(`SPAIN_2005 = 1367354866`, …, `SEASON_2005 = <revid printed by the script>`):

| revid | page |
|-------|------|
| 1367354866 | 2005 Spanish motorcycle Grand Prix |
| 1377682352 | 2024 Qatar motorcycle Grand Prix |
| 1373574739 | 2003 Grand Prix motorcycle racing season |
| 1386901932 | 2024 MotoGP World Championship |
| 1387261184 | Marc Márquez |
| (latest at fetch time) | 2005 Grand Prix motorcycle racing season |

README states: content from English Wikipedia, CC BY-SA 4.0, used as test fixtures.

- [ ] **Step 6: Commit** — `git commit -m "feat(ingest): Wikipedia API client with retries, HTML cache, fixtures"`

---

### Task 3: Domain models and Grand Prix results parser

**Files:**
- Create: `src/paddock/models.py`, `src/paddock/ingest/html_utils.py`, `src/paddock/ingest/race_parser.py`,
  `tests/ingest/test_race_parser.py`, `tests/conftest.py` (add `load_fixture(revid) -> str`)

**Interfaces:**
- Produces in `models.py`:
  - `class SessionType(StrEnum)`: `RACE = "race"`, `SPRINT = "sprint"`.
  - `class ResultStatus(StrEnum)`: `CLASSIFIED`, `RET`, `NC`, `DNS`, `DNQ`, `DSQ`, `EXC`, `WD` (values = names).
    Helper `ResultStatus.counts_as_start` property: `False` for `DNS`, `DNQ`, `WD`, `EXC`; `True` otherwise.
  - `ResultRow` (frozen): `session: SessionType`, `position: int | None`, `status: ResultStatus`,
    `rider_name: str`, `rider_link: str | None` (linked page title, spaces not underscores, URL-decoded),
    `rider_has_article: bool`, `bike_number: int | None`, `team: str`, `constructor: str`, `laps: int | None`,
    `grid: int | None`, `points: Decimal`.
- Produces in `race_parser.py`: `parse_gp_results(html: str) -> list[ResultRow]` — MotoGP race and sprint only.
- Produces in `html_utils.py`: `cell_text(tag: Tag) -> str` (visible text, footnote `<sup>` removed, whitespace
  collapsed); `link_target(tag: Tag) -> tuple[str | None, bool]` (page title, exists?).

Table selection rule (verified on 2005 and 2024 pages): a `table.wikitable` whose header row contains `Pos.`,
`Rider`, `Laps`, `Time/Retired`, `Grid`, `Points`. Its nearest preceding heading decides the session:
contains `Sprint` → `SPRINT`; else contains `MotoGP` → `RACE`; anything else (250 cc, Moto2, Moto3, 125 cc) is
skipped. Columns are found **by header name**, never position (2005 has `Team, Manufacturer`; 2024 has
`Team, Constructor`; both map to `team`, `constructor`). Rows with fewer cells than headers (e.g. `Sources: …`)
are skipped. `Pos.` cell: integer → `CLASSIFIED` with position; `Ret`/`NC`/`DNS`/`DNQ`/`DSQ`/`EX`/`WD` → that
status (`EX` → `EXC`), position `None`. Empty points → `Decimal(0)`; `12.5` → `Decimal("12.5")`. Grid `PL`
(pit lane) or empty → `None`.

- [ ] **Step 1: Write failing tests**

```python
def test_2005_spain_has_only_motogp_race_rows():
    rows = parse_gp_results(load_fixture(1367354866))
    assert len(rows) == 21
    assert {r.session for r in rows} == {SessionType.RACE}
    assert "Daniel Pedrosa" not in {r.rider_name for r in rows}  # 250cc winner must be excluded

def test_2005_spain_winner_row():
    rossi = next(r for r in parse_gp_results(load_fixture(1367354866)) if r.rider_name == "Valentino Rossi")
    assert (rossi.position, rossi.status, rossi.grid, rossi.points) == (1, ResultStatus.CLASSIFIED, 1, Decimal(25))
    assert (rossi.team, rossi.constructor, rossi.bike_number) == ("Gauloises Yamaha Team", "Yamaha", 46)
    assert rossi.rider_link == "Valentino Rossi" and rossi.rider_has_article

def test_2005_spain_retirement_row():
    hayden = next(r for r in parse_gp_results(load_fixture(1367354866)) if r.rider_name == "Nicky Hayden")
    assert (hayden.position, hayden.status, hayden.grid, hayden.points, hayden.laps) == (
        None, ResultStatus.RET, 4, Decimal(0), 20)

def test_2024_qatar_has_race_and_sprint():
    rows = parse_gp_results(load_fixture(1377682352))
    sprint_winner = next(r for r in rows if r.session is SessionType.SPRINT and r.position == 1)
    race_winner = next(r for r in rows if r.session is SessionType.RACE and r.position == 1)
    assert (sprint_winner.rider_name, sprint_winner.grid, sprint_winner.points) == ("Jorge Martín", 1, Decimal(12))
    assert (race_winner.rider_name, race_winner.grid, race_winner.points) == ("Francesco Bagnaia", 5, Decimal(25))
    assert race_winner.team == "Ducati Lenovo Team" and race_winner.constructor == "Ducati"
    assert "Arón Canet" not in {r.rider_name for r in rows}  # Moto2 excluded

def test_footnote_markers_are_stripped_from_numbers():  # Review Focus 3
    # synthetic table under <h2>MotoGP classification</h2>; Pos "1[a]", Points "12.5[note 2]", Grid "PL"
    assert (row.position, row.points, row.grid) == (1, Decimal("12.5"), None)

def test_status_codes_map_to_enum():
    # synthetic rows with Pos "DNS", "DSQ", "NC", "EX" -> DNS, DSQ, NC, EXC; position None
    ...

def test_red_link_rider_has_title_but_no_article():  # Review Focus 2
    # synthetic rider cell: <a href="/w/index.php?title=John_Doe&action=edit&redlink=1" class="new">John Doe</a>
    assert (row.rider_link, row.rider_has_article) == ("John Doe", False)
    # plain-text rider cell without link -> rider_link None, rider_has_article False
```

- [ ] **Step 2: Run** `uv run pytest tests/ingest/test_race_parser.py -q` — Expected: FAIL on assertions.
- [ ] **Step 3: Implement** `models.py`, `html_utils.py`, `race_parser.py` (BeautifulSoup with `"lxml"`).
- [ ] **Step 4: Run** — Expected: PASS; `uv run mypy` clean.
- [ ] **Step 5: Commit** — `git commit -m "feat(ingest): parse MotoGP race and sprint classifications"`

---

### Task 4: Season page parser

**Files:**
- Create: `src/paddock/ingest/season_parser.py`, `tests/ingest/test_season_parser.py`

**Interfaces:**
- Produces: `EventRef` (frozen, in `models.py`): `season: int`, `round: int`, `wiki_title: str`.
- Produces: `season_page_title(year: int) -> str` — `"{year} Grand Prix motorcycle racing season"` for
  `year <= LAST_LEGACY_TITLE_YEAR = 2011`, else `"{year} MotoGP World Championship"`.
- Produces: `parse_season_events(html: str, season: int) -> list[EventRef]`, ordered by round.

Rule (verified on 2003 and 2024): the results table is the `table.wikitable` whose header contains `Round`
and `Report`. For each row whose `Round` cell is an integer, the event title is the link target in the
`Report` cell (it points at the season-specific Grand Prix article, including irregular names such as
`2024 Motorcycle Grand Prix of the Americas`). Rows without a Report link (cancelled rounds) are skipped.

- [ ] **Step 1: Write failing tests**

```python
def test_season_title_rule():
    assert season_page_title(2002) == "2002 Grand Prix motorcycle racing season"
    assert season_page_title(2011) == "2011 Grand Prix motorcycle racing season"
    assert season_page_title(2012) == "2012 MotoGP World Championship"

def test_2003_events():
    events = parse_season_events(load_fixture(1373574739), 2003)
    assert len(events) == 16
    assert events[0] == EventRef(2003, 1, "2003 Japanese motorcycle Grand Prix")
    assert events[-1].wiki_title == "2003 Valencian Community motorcycle Grand Prix"

def test_2024_events_include_irregular_titles():
    events = parse_season_events(load_fixture(1386901932), 2024)
    assert len(events) == 20
    assert [e.round for e in events] == list(range(1, 21))
    assert "2024 Motorcycle Grand Prix of the Americas" in {e.wiki_title for e in events}
    assert events[-1].wiki_title == "2024 Solidarity motorcycle Grand Prix"
```

- [ ] **Step 2: Run** — Expected: FAIL. **Step 3: Implement.** **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(ingest): parse season calendars into Grand Prix references"`

---

### Task 5: Rider biography parser

**Files:**
- Create: `src/paddock/ingest/bio_parser.py`, `tests/ingest/test_bio_parser.py`

**Interfaces:**
- Produces: `BioSection` (frozen, in `models.py`): `ordinal: int` (0 = lead), `heading_path: tuple[str, ...]`
  (empty for lead), `text: str`, `year_from: int | None`, `year_to: int | None`, `team: str | None`.
- Produces: `HeadingMeta` (frozen): `year_from: int | None`, `year_to: int | None`, `team: str | None`, and
  `parse_heading_meta(heading: str) -> HeadingMeta`.
- Produces: `parse_bio(html: str) -> list[BioSection]`.

Rules: walk the top level of `div.mw-parser-output`; headings `h2`–`h4` maintain the heading stack (Parsoid
wraps them in `div.mw-heading`); collect text of `p`, `ul`, `ol` only — tables, infoboxes, figures, navboxes,
`sup.reference` and `span.mw-editsection` are ignored. Sections whose top-level heading is in
`EXCLUDED_SECTIONS = {"References", "Notes", "External links", "See also", "Further reading", "Bibliography",
"Career statistics", "Footnotes", "Citations", "Sources"}` are dropped, as are sections with empty text.
A section's metadata is its own heading's meta, with missing fields inherited from the nearest ancestor heading.

`parse_heading_meta` examples (each one a test case):

| heading | year_from | year_to | team |
|---------|-----------|---------|------|
| `2014: Domination` | 2014 | 2014 | None |
| `2008` | 2008 | 2008 | None |
| `Repsol Honda Team (2013–2023)` | 2013 | 2023 | `Repsol Honda Team` |
| `Ducati Lenovo Team (2025–)` | 2025 | None | `Ducati Lenovo Team` |
| `Gresini Racing MotoGP (2024)` | 2024 | 2024 | `Gresini Racing MotoGP` |
| `2015–2016: Struggles` | 2015 | 2016 | None |
| `125cc World Championship` | None | None | None |
| `Early life` | None | None | None |

Accept both `–` (en dash) and `-` as range separators.

- [ ] **Step 1: Write failing tests** — the table above as `@pytest.mark.parametrize`, plus:

```python
def test_marquez_sections():
    sections = parse_bio(load_fixture(1387261184))
    assert sections[0].heading_path == () and "Márquez" in sections[0].text
    domination = next(s for s in sections if s.heading_path[-1:] == ("2014: Domination",))
    assert (domination.year_from, domination.year_to, domination.team) == (2014, 2014, "Repsol Honda Team")
    assert not any(s.heading_path and s.heading_path[0] == "References" for s in sections)
    assert not any(re.search(r"\[\d+\]", s.text) for s in sections)  # citation markers removed
    assert [s.ordinal for s in sections] == list(range(len(sections)))
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(ingest): split rider articles into sections with year/team metadata"`

---

### Task 6: Manifest and snapshot builder

**Files:**
- Create: `src/paddock/ingest/manifest.py`, `src/paddock/ingest/snapshot.py`, `tests/ingest/test_snapshot.py`

**Interfaces:**
- Consumes: `WikiClient`, `HtmlCache` (Task 2); `parse_gp_results` (Task 3); `season_page_title`,
  `parse_season_events` (Task 4).
- Produces in `manifest.py`:
  - `class PageKind(StrEnum)`: `SEASON`, `EVENT`, `RIDER` (values lower-case).
  - `ManifestPage` (frozen): `kind: PageKind`, `title: str`, `revid: int`, `season: int | None`, `round: int | None`.
  - `Manifest` (frozen): `snapshot_date: date`, `first_season: int`, `last_season: int`,
    `pages: tuple[ManifestPage, ...]`, `rider_aliases: dict[str, str]` (linked title → canonical title).
  - `read_manifest(path: Path) -> Manifest`; `write_manifest(manifest: Manifest, path: Path) -> None` — JSON,
    sorted keys, written to a temp file then `os.replace` (atomic).
- Produces in `snapshot.py`:
  - `build_snapshot(client: WikiClient, cache: HtmlCache, today: date, first_season: int = FIRST_SEASON) -> Manifest`
    with `FIRST_SEASON = 2002`.
  - `ensure_cached(manifest: Manifest, client: WikiClient, cache: HtmlCache) -> int` — downloads pages missing
    from the cache, returns how many were fetched.
  - `IncompleteSeasonError(Exception)` carrying `season: int` and `titles: list[str]`.

Algorithm:

```
for year in first_season .. today.year:
    season page revision via latest_revisions; missing page -> stop the loop
    html = cache or fetch; events = parse_season_events(html, year)
    for each event: revision, html, results = parse_gp_results(html)
    events_without_race = [e for e in events if no RACE rows]
    if events_without_race or not events:
        if year >= today.year: stop the loop (season excluded, not an error)
        else: raise IncompleteSeasonError(year, titles)
    last_season = year
rider links = distinct rider_link of all results with rider_has_article
revisions = latest_revisions(rider links)  -> rider_aliases[link] = canonical_title; fetch each canonical page once
return Manifest(...)
```

The CLI (Task 8) writes the manifest; `build_snapshot` itself never writes it, so a failure mid-way leaves the
previous manifest untouched.

- [ ] **Step 1: Write failing tests** — use a `FakeWikiClient` (same two methods, in-memory dict of
  title → (canonical, revid) and revid → html) built from the fixtures plus tiny synthetic HTML.

```python
def test_manifest_roundtrip(tmp_path): ...  # write then read gives an equal Manifest

def test_snapshot_collects_seasons_events_and_riders(): ...
    # fake: one season (2005) with one event (2005 Spanish GP fixture) and riders' pages present;
    # today = 2006-01-10, season 2006 page missing -> loop stops
    assert manifest.last_season == 2005
    assert {p.kind for p in manifest.pages} == {PageKind.SEASON, PageKind.EVENT, PageKind.RIDER}
    assert sum(p.kind is PageKind.RIDER for p in manifest.pages) == 21

def test_current_season_without_results_is_excluded(): ...
    # 2005 complete, 2006 = today.year, its event has no MotoGP race table -> last_season == 2005, no error

def test_incomplete_past_season_raises_with_page_title():  # Review Focus 5
    with pytest.raises(IncompleteSeasonError) as err:
        build_snapshot(fake, cache, today=date(2007, 1, 1))
    assert err.value.season == 2006 and "2006 Broken motorcycle Grand Prix" in err.value.titles

def test_snapshot_maps_redirected_rider_links_to_one_canonical_title():  # Review Focus 1
    # two events link "Dani Pedrosa" and "Daniel Pedrosa"; fake redirects the latter to the former
    assert manifest.rider_aliases["Daniel Pedrosa"] == "Dani Pedrosa"
    assert sum(p.title == "Dani Pedrosa" for p in manifest.pages) == 1

def test_ensure_cached_fetches_only_missing(tmp_path): ...  # 1 of 3 pages cached -> returns 2
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(ingest): pinned snapshot builder with completeness rule and rider aliases"`

---

### Task 7: Database schema and loader

**Files:**
- Create: `src/paddock/db/__init__.py`, `src/paddock/db/schema.sql`, `src/paddock/db/connection.py`,
  `src/paddock/db/loader.py`, `tests/db/test_loader.py`; Modify: `tests/conftest.py` (db fixture)

**Interfaces:**
- Consumes: `Manifest`, `PageKind` (Task 6); parsers (Tasks 3–5); `HtmlCache` (Task 2).
- Produces: `connect(url: str) -> psycopg.Connection`; `apply_schema(conn) -> None` (executes `schema.sql`,
  idempotent).
- Produces: `load_snapshot(conn: psycopg.Connection, manifest: Manifest, cache: HtmlCache) -> LoadStats`,
  `LoadStats` (frozen): `seasons: int`, `events: int`, `riders: int`, `results: int`, `bio_sections: int`.
  Rebuilds all tables in **one transaction** (`TRUNCATE ... RESTART IDENTITY CASCADE`, then inserts).
  Raises `MissingCachedPageError(revid, title)` if a manifest page is not in the cache.

Schema (`schema.sql`, all `CREATE ... IF NOT EXISTS`):

```sql
CREATE EXTENSION IF NOT EXISTS vector;            -- used from stage 2
CREATE TYPE session_type AS ENUM ('race', 'sprint');             -- guarded with DO $$ ... $$ for idempotency
CREATE TYPE result_status AS ENUM ('CLASSIFIED','RET','NC','DNS','DNQ','DSQ','EXC','WD');
seasons(year int PK, wiki_title text NOT NULL, revid bigint NOT NULL)
events(id serial PK, season_year int REFERENCES seasons, round int NOT NULL, wiki_title text UNIQUE NOT NULL,
       revid bigint NOT NULL, UNIQUE (season_year, round))
riders(id serial PK, name text NOT NULL, wiki_title text UNIQUE, revid bigint)   -- wiki_title NULL = no article
results(id serial PK, event_id int REFERENCES events, rider_id int REFERENCES riders, session session_type,
        position int, status result_status NOT NULL, grid int, points numeric(5,1) NOT NULL DEFAULT 0,
        laps int, team text NOT NULL, constructor text NOT NULL, bike_number int,
        UNIQUE (event_id, session, rider_id),
        CHECK ((status = 'CLASSIFIED') = (position IS NOT NULL)))
bio_sections(id serial PK, rider_id int REFERENCES riders, ordinal int NOT NULL, heading_path text[] NOT NULL,
             text text NOT NULL, year_from int, year_to int, team text, source_url text NOT NULL,
             UNIQUE (rider_id, ordinal))
VIEW rider_seasons: DISTINCT rider_id, season_year, team, constructor FROM results JOIN events WHERE session='race'
```

Rider identity: a result's rider is `rider_aliases.get(rider_link, rider_link)` when the link has an article;
if that title has no `RIDER` page in the manifest, the rider row gets that `wiki_title`, `revid NULL` and no bio
sections. Without an article, the rider is matched by `name` among riders with `wiki_title IS NULL`.
`source_url` = `https://en.wikipedia.org/w/index.php?oldid=<revid>`.

- [ ] **Step 1: Write failing tests** (all `@pytest.mark.db`; fixture creates schema in `paddock_test`, truncates
  per test). `mini_manifest` is built in-test from fixtures: season pages 2005 (`SEASON_2005`) and 2024, events
  2005 Spanish GP (round 1) and 2024 Qatar GP (round 1), rider page Marc Márquez; `fixture_cache` is
  `HtmlCache(tests/fixtures/wiki)`.

```python
def test_load_counts(db, mini_manifest, fixture_cache):
    stats = load_snapshot(db, mini_manifest, fixture_cache)
    expected = len(parse_gp_results(load_fixture(SPAIN_2005))) + len(parse_gp_results(load_fixture(QATAR_2024)))
    assert (stats.seasons, stats.events, stats.results) == (2, 2, expected)

def test_retirement_is_ret_not_crash(db, ...):
    assert db.execute("SELECT status FROM results JOIN riders r ON r.id = rider_id "
                      "WHERE r.name = 'Nicky Hayden'").fetchone() == ("RET",)

def test_load_merges_aliased_rider_links(db, ...):  # Review Focus 1
    # manifest.rider_aliases maps two link titles to one canonical page -> one riders row

def test_rider_without_article_is_loaded(db, ...):  # Review Focus 2
    # synthetic event page with a red-link rider -> riders row with wiki_title NULL and its result row

def test_rider_seasons_view(db, ...):
    rows = db.execute("SELECT team, constructor FROM rider_seasons rs JOIN riders r ON r.id = rs.rider_id "
                      "WHERE r.name = 'Francesco Bagnaia' AND season_year = 2024").fetchall()
    assert rows == [("Ducati Lenovo Team", "Ducati")]

def test_bio_sections_loaded_with_metadata(db, ...):
    assert db.execute("SELECT year_from, team FROM bio_sections WHERE heading_path[array_length(heading_path,1)]"
                      " = '2014: Domination'").fetchone() == (2014, "Repsol Honda Team")

def test_reload_is_idempotent(db, ...):  # loading twice gives identical counts

def test_missing_cached_page_raises(db, ...):  # MissingCachedPageError names the page
```

- [ ] **Step 2: Run** `docker compose up -d db && uv run pytest -m db -q` — FAIL.
- [ ] **Step 3: Implement.** **Step 4: Run** — PASS; `uv run pytest -q -m "not db"` also passes without Docker.
- [ ] **Step 5: Commit** — `git commit -m "feat(db): schema and snapshot loader"`

---

### Task 8: CLI, real snapshot, sanity checks, README

**Files:**
- Create: `src/paddock/cli.py`, `tests/test_cli.py`, `snapshot/manifest.json` (generated); Modify: `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: `main(argv: Sequence[str] | None = None) -> int` with argparse subcommands:
  - `paddock ingest snapshot` → `build_snapshot` with `today=date.today()`, then `write_manifest`, then logs counts.
  - `paddock ingest fetch` → `read_manifest` + `ensure_cached`.
  - `paddock ingest load` → `connect`, `apply_schema`, `load_snapshot`, logs `LoadStats`.

- [ ] **Step 1: Write failing tests** — `test_snapshot_command_writes_manifest_only_on_success` (patch
  `build_snapshot` to raise → manifest file unchanged; to return → file written) and
  `test_unknown_command_returns_nonzero`.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.

- [ ] **Step 5: Real run**

Run: `uv run paddock ingest snapshot` (expect several minutes; ~25 season, ~450 event, ~200 rider pages)
Expected: manifest written; log shows `last_season` (2025, or 2026 if all 2026 Grand Prix pages already have
MotoGP race tables).
Run: `uv run paddock ingest load` — Expected: `LoadStats` logged, no errors.

If `IncompleteSeasonError` is raised for a past season, inspect the named page, extend the parser with a
fixture test for that page's table shape, and re-run. Do not skip the season.

- [ ] **Step 6: Sanity checks against known facts** (psql on the `paddock` db)

| check | expected |
|-------|----------|
| events in 2003 / 2024 | 16 / 20 |
| Rossi race wins, all seasons in data (2002+) | 76 |
| Márquez race wins in 2014 | 13 |
| Bagnaia race wins (session `race`) in 2024 | 11 |
| any `results` row with `status='CLASSIFIED'` and `position IS NULL` | none (CHECK) |
| riders with more than one `wiki_title` variant for the same person (eyeball `SELECT name, count(*) … GROUP BY name HAVING count(*) > 1`) | none |

Any mismatch is a parser bug: add a failing fixture test, fix, re-load.

- [ ] **Step 7: README** — setup (`uv sync`, `docker compose up -d db`), the three ingest commands, data
  attribution (Wikipedia, CC BY-SA), and a short "how ingestion works" paragraph (snapshot → fetch → load).

- [ ] **Step 8: Commit and merge**

```bash
git add -A && git commit -m "feat: ingest CLI, pinned snapshot manifest, README"
git checkout main && git merge --no-ff stage-1-ingestion && git push origin main
```
