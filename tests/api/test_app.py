import pytest
from fastapi.testclient import TestClient

from paddock.api import app as app_module
from paddock.api.answering import STUB_ANSWER
from paddock.api.app import create_app
from paddock.api.schemas import MAX_QUESTION_LENGTH, AskResponse


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}


def test_ask_returns_stub_contract(client: TestClient) -> None:
    response = client.post("/api/ask", json={"question": "Who is Marc Márquez?"})
    assert response.status_code == 200
    assert response.json() == {"answer": STUB_ANSWER, "question_type": None, "sources": [], "sql": None}


def test_ask_rejects_blank_question(client: TestClient) -> None:
    assert client.post("/api/ask", json={"question": "   "}).status_code == 422


def test_ask_rejects_too_long_question(client: TestClient) -> None:
    assert client.post("/api/ask", json={"question": "x" * (MAX_QUESTION_LENGTH + 1)}).status_code == 422


def test_ask_accepts_question_of_max_length(client: TestClient) -> None:
    assert client.post("/api/ask", json={"question": "x" * MAX_QUESTION_LENGTH}).status_code == 200


def test_ask_passes_stripped_question_to_answering(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def recording(question: str) -> AskResponse:
        seen.append(question)
        return AskResponse(answer="ok", question_type=None, sources=[], sql=None)

    monkeypatch.setattr(app_module, "answer_question", recording)
    client.post("/api/ask", json={"question": "  Rossi?  "})
    assert seen == ["Rossi?"]
