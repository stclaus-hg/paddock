from fastapi import FastAPI

from paddock.api.answering import answer_question
from paddock.api.schemas import AskRequest, AskResponse


def create_app() -> FastAPI:
    api = FastAPI(title="Paddock", summary="Ask anything about MotoGP riders.")

    @api.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.post("/api/ask")
    def ask(request: AskRequest) -> AskResponse:
        return answer_question(request.question)

    return api


app = create_app()
