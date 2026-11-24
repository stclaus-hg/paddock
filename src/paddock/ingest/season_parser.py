"""Season page → ordered references to its Grand Prix articles."""

from bs4 import BeautifulSoup, Tag

from paddock.ingest.html_utils import cell_text, expand_row, link_target
from paddock.models import EventRef

#: the last season whose Wikipedia article uses the "Grand Prix motorcycle racing season" title
LAST_LEGACY_TITLE_YEAR = 2011
ROUND_HEADER = "Round"
REPORT_HEADER = "Report"


def season_page_title(year: int) -> str:
    if year <= LAST_LEGACY_TITLE_YEAR:
        return f"{year} Grand Prix motorcycle racing season"
    return f"{year} MotoGP World Championship"


def parse_season_events(html: str, season: int) -> list[EventRef]:
    """Grand Prix of the season, in round order, taken from the results table's Report links.

    Rounds without a Report link (cancelled or not yet held) are left out.
    """
    soup = BeautifulSoup(html, "lxml")
    for table in soup.select("table.wikitable"):
        header_row = table.find("tr")
        if not isinstance(header_row, Tag):
            continue
        headers = [cell_text(c) for c in header_row.find_all(["th", "td"], recursive=False)]
        if ROUND_HEADER in headers and REPORT_HEADER in headers:
            return _events_from_table(table, headers, season)
    return []


def _events_from_table(table: Tag, headers: list[str], season: int) -> list[EventRef]:
    round_col, report_col = headers.index(ROUND_HEADER), headers.index(REPORT_HEADER)
    events: list[EventRef] = []
    for tr in table.find_all("tr")[1:]:
        cells = expand_row(tr)
        if cells is None or len(cells) < len(headers):
            continue
        round_text = cell_text(cells[round_col])
        title, _ = link_target(cells[report_col])
        if round_text.isdigit() and title is not None:
            events.append(EventRef(season, int(round_text), title))
    return sorted(events, key=lambda e: e.round)
