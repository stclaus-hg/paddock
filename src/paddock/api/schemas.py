from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

MAX_QUESTION_LENGTH = 500  #: longest question the API accepts, in characters


class QuestionType(StrEnum):
    BIO = "bio"
    STATS = "stats"
    MIXED = "mixed"
    OUT_OF_SCOPE = "out_of_scope"


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)


class Source(BaseModel):
    title: str
    url: str


class AskResponse(BaseModel):
    answer: str
    question_type: QuestionType | None
    sources: list[Source]
    sql: str | None
