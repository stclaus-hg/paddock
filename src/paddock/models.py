from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class SessionType(StrEnum):
    RACE = "race"
    SPRINT = "sprint"


class ResultStatus(StrEnum):
    CLASSIFIED = "CLASSIFIED"
    RET = "RET"  #: retired from the race — never assume a crash
    NC = "NC"  #: finished but not classified
    DNS = "DNS"
    DNQ = "DNQ"
    DSQ = "DSQ"
    EXC = "EXC"
    WD = "WD"

    @property
    def counts_as_start(self) -> bool:
        return self not in _NON_STARTS


_NON_STARTS = frozenset({ResultStatus.DNS, ResultStatus.DNQ, ResultStatus.WD, ResultStatus.EXC})


@dataclass(frozen=True)
class ResultRow:
    session: SessionType
    position: int | None
    status: ResultStatus
    rider_name: str
    rider_link: str | None  #: linked page title (spaces, URL-decoded); None for plain-text riders
    rider_has_article: bool
    bike_number: int | None
    team: str
    constructor: str
    laps: int | None
    grid: int | None
    points: Decimal


@dataclass(frozen=True)
class EventRef:
    season: int
    round: int
    wiki_title: str


@dataclass(frozen=True)
class BioSection:
    ordinal: int  #: 0 is the lead section
    heading_path: tuple[str, ...]  #: headings from the top level down; empty for the lead
    text: str
    year_from: int | None
    year_to: int | None
    team: str | None
