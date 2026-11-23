from decimal import Decimal

import pytest

from paddock.ingest.race_parser import parse_gp_results
from paddock.models import ResultRow, ResultStatus, SessionType
from tests.wiki_fixtures import QATAR_2024, SPAIN_2005, load_fixture

HEADER = (
    "<tr><th>Pos.</th><th>No.</th><th>Rider</th><th>Team</th><th>Constructor</th>"
    "<th>Laps</th><th>Time/Retired</th><th>Grid</th><th>Points</th></tr>"
)
FLAG = '<span class="flagicon"><a href="/wiki/Spain" title="Spain"><img alt="Spain"/></a></span> '


def synthetic_page(*rows: str, heading: str = "MotoGP classification") -> str:
    body = "".join(f"<tr>{r}</tr>" for r in rows)
    return (
        f'<div class="mw-parser-output"><div class="mw-heading mw-heading2"><h2>{heading}</h2></div>'
        f'<table class="wikitable">{HEADER}{body}</table></div>'
    )


def row(
    pos: str, rider: str = f'{FLAG}<a href="/wiki/Some_Rider">Some Rider</a>', grid: str = "3", points: str = ""
) -> str:
    return (
        f"<th>{pos}</th><td>7</td><td>{rider}</td><td>Team X</td><td>Honda</td>"
        f"<td>20</td><td>+1.000</td><td>{grid}</td><td>{points}</td>"
    )


def only_row(html: str) -> ResultRow:
    rows = parse_gp_results(html)
    assert len(rows) == 1
    return rows[0]


def test_2005_spain_has_only_motogp_race_rows():
    rows = parse_gp_results(load_fixture(SPAIN_2005))
    assert len(rows) == 21
    assert {r.session for r in rows} == {SessionType.RACE}
    assert "Daniel Pedrosa" not in {r.rider_name for r in rows}  # 250cc winner must be excluded


def test_2005_spain_winner_row():
    rossi = next(r for r in parse_gp_results(load_fixture(SPAIN_2005)) if r.rider_name == "Valentino Rossi")
    assert (rossi.position, rossi.status, rossi.grid, rossi.points) == (1, ResultStatus.CLASSIFIED, 1, Decimal(25))
    assert (rossi.team, rossi.constructor, rossi.bike_number) == ("Gauloises Yamaha Team", "Yamaha", 46)
    assert rossi.rider_link == "Valentino Rossi"
    assert rossi.rider_has_article


def test_2005_spain_retirement_row():
    hayden = next(r for r in parse_gp_results(load_fixture(SPAIN_2005)) if r.rider_name == "Nicky Hayden")
    assert (hayden.position, hayden.status, hayden.grid, hayden.points, hayden.laps) == (
        None,
        ResultStatus.RET,
        4,
        Decimal(0),
        20,
    )


def test_2024_qatar_has_race_and_sprint():
    rows = parse_gp_results(load_fixture(QATAR_2024))
    sprint_winner = next(r for r in rows if r.session is SessionType.SPRINT and r.position == 1)
    race_winner = next(r for r in rows if r.session is SessionType.RACE and r.position == 1)
    assert (sprint_winner.rider_name, sprint_winner.grid, sprint_winner.points) == ("Jorge Martín", 1, Decimal(12))
    assert (race_winner.rider_name, race_winner.grid, race_winner.points) == ("Francesco Bagnaia", 5, Decimal(25))
    assert race_winner.team == "Ducati Lenovo Team"
    assert race_winner.constructor == "Ducati"
    assert "Arón Canet" not in {r.rider_name for r in rows}  # Moto2 excluded


def test_footnote_markers_are_stripped_from_numbers():  # Review Focus 3
    ref = '<sup class="reference"><a href="#cite_note-1">[a]</a></sup>'
    note = '<sup class="reference"><a href="#cite_note-2">[note 2]</a></sup>'
    result = only_row(synthetic_page(row(f"1{ref}", grid="PL", points=f"12.5{note}")))
    assert (result.position, result.points, result.grid) == (1, Decimal("12.5"), None)


@pytest.mark.parametrize(
    ("pos", "status"),
    [
        ("DNS", ResultStatus.DNS),
        ("DSQ", ResultStatus.DSQ),
        ("NC", ResultStatus.NC),
        ("EX", ResultStatus.EXC),
        ("Ret", ResultStatus.RET),
        ("DNQ", ResultStatus.DNQ),
        ("WD", ResultStatus.WD),
    ],
)
def test_status_codes_map_to_enum(pos, status):
    result = only_row(synthetic_page(row(pos)))
    assert (result.status, result.position) == (status, None)


def test_unknown_position_code_fails_loudly():
    with pytest.raises(ValueError, match="XYZ"):
        parse_gp_results(synthetic_page(row("XYZ")))


def test_red_link_rider_has_title_but_no_article():  # Review Focus 2
    red = f'{FLAG}<a href="/w/index.php?title=John_Doe&amp;action=edit&amp;redlink=1" class="new">John Doe</a>'
    result = only_row(synthetic_page(row("1", rider=red)))
    assert (result.rider_name, result.rider_link, result.rider_has_article) == ("John Doe", "John Doe", False)


def test_plain_text_rider_has_no_link():  # Review Focus 2
    result = only_row(synthetic_page(row("1", rider=f"{FLAG}Jane Roe")))
    assert (result.rider_name, result.rider_link, result.rider_has_article) == ("Jane Roe", None, False)


def test_rider_link_is_url_decoded_without_fragment():
    link = f'{FLAG}<a href="/wiki/Jorge_Mart%C3%ADn#Career">Jorge Martín</a>'
    assert only_row(synthetic_page(row("1", rider=link))).rider_link == "Jorge Martín"


def test_sprint_heading_gives_sprint_session():
    result = only_row(synthetic_page(row("1"), heading="MotoGP Sprint"))
    assert result.session is SessionType.SPRINT


def test_other_class_headings_are_skipped():
    assert parse_gp_results(synthetic_page(row("1"), heading="Moto2")) == []


def test_status_counts_as_start():
    assert ResultStatus.RET.counts_as_start
    assert ResultStatus.CLASSIFIED.counts_as_start
    assert not ResultStatus.DNS.counts_as_start
    assert not ResultStatus.DNQ.counts_as_start


def test_row_with_merged_cells_is_parsed():
    merged = (
        f'<th>DNS</th><td>7</td><td>{FLAG}<a href="/wiki/Some_Rider">Some Rider</a></td><td>Team X</td>'
        '<td>Honda</td><td colspan="2">Did not start</td><td>9</td><td></td>'
    )
    result = only_row(synthetic_page(merged))
    assert (result.status, result.laps, result.grid, result.team) == (ResultStatus.DNS, None, 9, "Team X")
