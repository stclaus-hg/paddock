# App Skeleton — FastAPI Backend and React Chat — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A running end-to-end shell: a React chat page sends a question to a FastAPI endpoint and renders the
answer, its sources and the SQL used. The endpoint returns a stub answer until the RAG core is wired in.

**Architecture:** Owner's decision (2026-11-23): build spec stages 5–6 as an empty shell *before* stage 1, so the
RAG core later plugs into a working app. The response contract (`answer`, `question_type`, `sources`, `sql`) is
fixed now from spec §8.2 items 7 and 10; only the function producing it changes later. The Vite dev server
proxies `/api` to FastAPI, so no CORS setup is needed.

**Tech Stack:** Python 3.14, uv, FastAPI, uvicorn, pytest; Node 22 (`.nvmrc`), Vite, React, TypeScript, Vitest,
Testing Library.

**Spec:** `docs/specs/2026-11-21-motogp-rag-design.md` (§8.2 items 7 and 10, §8.4, §9.1).

**Branch:** `app-skeleton`, merged to `main` after Task 4.

**Relationship to stage 1 plan:** Task 1 here *is* Task 1 of `docs/plans/2026-11-23-stage-1-ingestion.md`
(project scaffold, tooling, docker-compose on host port 5434). Execute it from that plan, on this branch;
stage 1 then starts at its Task 2.

## Global Constraints

- All constraints of the stage 1 plan apply to Python code.
- Frontend: TypeScript strict (Vite template default), no UI framework or CSS library — the UI stays minimal
  (spec §3). Node version pinned in `frontend/.nvmrc` = `22`.
- Ports: FastAPI `8000`, Vite `5173`, Postgres `5434`.
- `MAX_QUESTION_LENGTH = 500` characters, enforced by the backend.

## Review Focus

1. **Whitespace-only question** — must be rejected (422), not answered. Test in Task 2
   (`test_ask_rejects_blank_question`).
2. **Backend down or returning 5xx** — the chat must show an error message and stay usable. Test in Task 3
   (`shows an error and re-enables input when the request fails`).
3. **Double submit while a request is pending** — the button is disabled until the answer arrives. Test in
   Task 3 (`disables sending while a request is pending`).
4. **Answer with no sources and no SQL** — renders just the answer, no empty "Sources"/"SQL" blocks. Test in
   Task 3 (`renders sources and SQL only when present`).
5. **Very long question (> 500 chars)** — rejected with 422. Test in Task 2 (`test_ask_rejects_too_long_question`).

---

## File Structure

```
src/paddock/api/__init__.py
src/paddock/api/schemas.py      # AskRequest, AskResponse, Source, QuestionType
src/paddock/api/answering.py    # answer_question() — stub now, RAG core later
src/paddock/api/app.py          # create_app(), module-level `app`
tests/api/test_app.py
frontend/                       # Vite React-TS app
  .nvmrc
  vite.config.ts                # /api proxy -> http://localhost:8000; vitest jsdom env
  src/types.ts                  # AskResponse, Source (mirror backend schema)
  src/api.ts                    # askQuestion()
  src/api.test.ts
  src/components/Chat.tsx
  src/components/Chat.css
  src/components/Chat.test.tsx
  src/App.tsx                   # header + <Chat />
```

---

### Task 1: Project scaffold

Execute **Task 1 of the stage 1 plan** verbatim (on branch `app-skeleton` instead of `stage-1-ingestion`).

---

### Task 2: FastAPI backend

**Files:** Create `src/paddock/api/{__init__,schemas,answering,app}.py`, `tests/api/test_app.py`;
Modify `pyproject.toml` (deps `fastapi`, `uvicorn[standard]`).

**Interfaces:**
- Produces in `schemas.py`:
  - `class QuestionType(StrEnum)`: `BIO = "bio"`, `STATS = "stats"`, `MIXED = "mixed"`, `OUT_OF_SCOPE = "out_of_scope"`.
  - `AskRequest(BaseModel)`: `question: str` — stripped, `min_length=1`, `max_length=MAX_QUESTION_LENGTH`.
  - `Source(BaseModel)`: `title: str`, `url: str`.
  - `AskResponse(BaseModel)`: `answer: str`, `question_type: QuestionType | None`, `sources: list[Source]`,
    `sql: str | None`.
- Produces in `answering.py`: `answer_question(question: str) -> AskResponse` — returns
  `STUB_ANSWER = "Paddock is not connected to its knowledge base yet."`, `question_type=None`, `sources=[]`, `sql=None`.
- Produces in `app.py`: `create_app() -> FastAPI` with `GET /api/health -> {"status": "ok"}` and
  `POST /api/ask` (`AskRequest -> AskResponse`); `app = create_app()`.

- [ ] **Step 1: Write failing tests** (`fastapi.testclient.TestClient(create_app())`)

```python
def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}

def test_ask_returns_stub_contract():
    body = client.post("/api/ask", json={"question": "Who is Marc Márquez?"}).json()
    assert body == {"answer": STUB_ANSWER, "question_type": None, "sources": [], "sql": None}

def test_ask_rejects_blank_question():        # Review Focus 1
    assert client.post("/api/ask", json={"question": "   "}).status_code == 422

def test_ask_rejects_too_long_question():     # Review Focus 5
    assert client.post("/api/ask", json={"question": "x" * (MAX_QUESTION_LENGTH + 1)}).status_code == 422

def test_ask_passes_stripped_question_to_answering(monkeypatch):
    # monkeypatch paddock.api.app.answer_question to record its argument
    client.post("/api/ask", json={"question": "  Rossi?  "})
    assert seen == ["Rossi?"]
```

- [ ] **Step 2: Run** `uv run pytest tests/api -q` — Expected: FAIL on assertions.
- [ ] **Step 3: Implement.** `str_strip_whitespace=True` in the request model config does the stripping.
- [ ] **Step 4: Run** tests, `uv run ruff check .`, `uv run mypy` — Expected: all clean.
  Run: `uv run uvicorn paddock.api.app:app --port 8000` and `curl -s localhost:8000/api/health` → `{"status":"ok"}`.
- [ ] **Step 5: Commit** — `git commit -m "feat(api): FastAPI skeleton with health and stub ask endpoint"`

---

### Task 3: React chat

**Files:** Create `frontend/` from the Vite `react-ts` template, then the files listed in File Structure.

**Interfaces:**
- Consumes: `POST /api/ask` contract from Task 2.
- Produces in `src/types.ts`: `type QuestionType = "bio" | "stats" | "mixed" | "out_of_scope"`;
  `interface Source { title: string; url: string }`;
  `interface AskResponse { answer: string; question_type: QuestionType | null; sources: Source[]; sql: string | null }`.
- Produces in `src/api.ts`: `askQuestion(question: string): Promise<AskResponse>` — `POST /api/ask` with JSON;
  non-2xx → `throw new Error(\`Request failed with status ${status}\`)`.
- Produces in `src/components/Chat.tsx`: `export function Chat(): JSX.Element` — a message list (user and
  assistant turns), a text input and a "Send" button. Enter submits. Assistant turn shows the answer, a
  "Sources" list of links (only if non-empty) and the SQL in a `<pre>` under "SQL" (only if non-null).

- [ ] **Step 1: Create the app**

```bash
cd /home/quantum/dev/pet/paddock && npm create vite@latest frontend -- --template react-ts
cd frontend && echo 22 > .nvmrc && nvm use && npm install
npm install -D vitest jsdom @testing-library/react @testing-library/user-event @testing-library/jest-dom
```

Add `"test": "vitest run"` to `package.json`; in `vite.config.ts` set `server.proxy = {"/api": "http://localhost:8000"}`
and `test = {environment: "jsdom", setupFiles: ["./src/setupTests.ts"]}` (setup imports `@testing-library/jest-dom/vitest`).
Remove the template's demo content and assets.

- [ ] **Step 2: Write failing tests**

```ts
// src/api.test.ts  (stub global fetch with vi.fn)
it("posts the question as JSON and returns the parsed body")
  // expect fetch called with "/api/ask", method POST, body JSON.stringify({question: "Rossi?"})
it("throws on a non-2xx response")
  // fetch resolves {ok: false, status: 500} -> rejects with "Request failed with status 500"

// src/components/Chat.test.tsx  (vi.mock("../api"))
it("sends the question and shows the answer")
  // type "Who is Rossi?" + Enter -> question text and mocked answer are on screen
it("renders sources and SQL only when present")          // Review Focus 4
  // answer with sources [{title: "Valentino Rossi", url: "https://en.wikipedia.org/..."}] and sql "SELECT 1"
  //   -> link "Valentino Rossi" with that href, and "SELECT 1" in a <pre>
  // answer with [] and null -> queryByText("Sources") and queryByText("SQL") are null
it("disables sending while a request is pending")        // Review Focus 3
  // askQuestion returns a never-resolving promise -> button disabled after submit
it("shows an error and re-enables input when the request fails")   // Review Focus 2
  // askQuestion rejects -> text "Something went wrong" visible; button enabled after typing again
it("does not send an empty question")
  // button disabled while input is empty or whitespace
```

- [ ] **Step 3: Run** `npm test` — Expected: FAIL.
- [ ] **Step 4: Implement** `types.ts`, `api.ts`, `Chat.tsx`, `Chat.css`, `App.tsx` (header "Paddock" + tagline
  "Ask anything about MotoGP riders" + `<Chat />`).
- [ ] **Step 5: Run** `npm test && npm run build && npm run lint` — Expected: all pass.
- [ ] **Step 6: Commit** — `git commit -m "feat(frontend): React chat skeleton wired to /api/ask"`

---

### Task 4: End-to-end check and README

- [ ] **Step 1: Run both servers**
  `uv run uvicorn paddock.api.app:app --port 8000` and `cd frontend && npm run dev`.
- [ ] **Step 2: Verify in a browser** at `http://localhost:5173`: ask a question → the stub answer appears;
  stop the backend, ask again → the error message appears.
- [ ] **Step 3: README** — "Running the app" section: prerequisites (uv, Node 22 via `.nvmrc`, Docker), the two
  commands above, and a note that answers are a stub until the RAG core is connected.
- [ ] **Step 4: Commit and merge**

```bash
git add -A && git commit -m "docs: how to run the app skeleton"
git checkout main && git merge --no-ff app-skeleton && git push origin main
```
