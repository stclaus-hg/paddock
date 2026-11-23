from paddock.api.schemas import AskResponse

STUB_ANSWER = "Paddock is not connected to its knowledge base yet."  #: placeholder until the RAG core is wired in


def answer_question(question: str) -> AskResponse:
    return AskResponse(answer=STUB_ANSWER, question_type=None, sources=[], sql=None)
