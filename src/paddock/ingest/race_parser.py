"""Grand Prix page → MotoGP race and sprint classification rows."""

from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup, Tag

from paddock.ingest.html_utils import cell_text, link_target
from paddock.models import ResultRow, ResultStatus, SessionType

#: header cells that identify a race classification table (qualifying and practice tables lack some of them)
REQUIRED_HEADERS = frozenset({"Pos.", "Rider", "Laps", "Time/Retired", "Grid", "Points"})
#: older pages call the constructor column "Manufacturer"
CONSTRUCTOR_HEADERS = ("Constructor", "Manufacturer")
SPRINT_MARKER = "Sprint"
PREMIER_CLASS_MARKER = "MotoGP"
HEADING_TAGS = ("h2", "h3", "h4")

#: non-numeric Pos. cell values, upper-cased
STATUS_CODES = {
    "RET": ResultStatus.RET,
    "NC": ResultStatus.NC,
    "DNS": ResultStatus.DNS,
    "DNQ": ResultStatus.DNQ,
    "DSQ": ResultStatus.DSQ,
    "EX": ResultStatus.EXC,
    "EXC": ResultStatus.EXC,
    "WD": ResultStatus.WD,
}


def parse_gp_results(html: str) -> list[ResultRow]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[ResultRow] = []
    for table in soup.select("table.wikitable"):
        header_row = table.find("tr")
        if not isinstance(header_row, Tag):
            continue
        headers = [cell_text(c) for c in header_row.find_all(["th", "td"], recursive=False)]
        if not REQUIRED_HEADERS.issubset(headers):
            continue
        session = _session_for(table)
        if session is None:
            continue
        rows.extend(_parse_table(table, headers, session))
    return rows


def _session_for(table: Tag) -> SessionType | None:
    heading = table.find_previous(HEADING_TAGS)
    title = cell_text(heading) if isinstance(heading, Tag) else ""
    if SPRINT_MARKER in title:
        return SessionType.SPRINT
    if PREMIER_CLASS_MARKER in title:
        return SessionType.RACE
    return None


def _parse_table(table: Tag, headers: list[str], session: SessionType) -> list[ResultRow]:
    column = {name: i for i, name in enumerate(headers)}
    constructor_col = next((column[h] for h in CONSTRUCTOR_HEADERS if h in column), None)
    rows: list[ResultRow] = []
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) < len(headers):
            continue  # footer rows such as "Sources: …" span all columns in one cell

        def text(name: str, cells: list[Tag] = cells) -> str:
            return cell_text(cells[column[name]]) if name in column else ""

        position, status = _position_and_status(text("Pos."))
        rider_cell = cells[column["Rider"]]
        rider_link, has_article = link_target(rider_cell)
        rows.append(
            ResultRow(
                session=session,
                position=position,
                status=status,
                rider_name=cell_text(rider_cell),
                rider_link=rider_link,
                rider_has_article=has_article,
                bike_number=_int_or_none(text("No.")),
                team=text("Team"),
                constructor=cell_text(cells[constructor_col]) if constructor_col is not None else "",
                laps=_int_or_none(text("Laps")),
                grid=_int_or_none(text("Grid")),
                points=_points(text("Points")),
            )
        )
    return rows


def _position_and_status(value: str) -> tuple[int | None, ResultStatus]:
    if value.isdigit():
        return int(value), ResultStatus.CLASSIFIED
    status = STATUS_CODES.get(value.upper())
    if status is None:
        raise ValueError(f"Unknown position code in results table: {value!r}")
    return None, status


def _int_or_none(value: str) -> int | None:
    """Integer cells; anything else (empty, "PL" for a pit-lane start) means no value."""
    return int(value) if value.isdigit() else None


def _points(value: str) -> Decimal:
    if not value:
        return Decimal(0)
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Unparseable points value: {value!r}") from exc
