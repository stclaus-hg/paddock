from paddock.ingest.season_parser import parse_season_events, season_page_title
from paddock.models import EventRef
from tests.wiki_fixtures import SEASON_2003, SEASON_2005, SEASON_2024, load_fixture


def test_season_title_rule():
    assert season_page_title(2002) == "2002 Grand Prix motorcycle racing season"
    assert season_page_title(2011) == "2011 Grand Prix motorcycle racing season"
    assert season_page_title(2012) == "2012 MotoGP World Championship"


def test_2003_events():
    events = parse_season_events(load_fixture(SEASON_2003), 2003)
    assert len(events) == 16
    assert events[0] == EventRef(2003, 1, "2003 Japanese motorcycle Grand Prix")
    assert events[-1].wiki_title == "2003 Valencian Community motorcycle Grand Prix"


def test_2005_events():
    events = parse_season_events(load_fixture(SEASON_2005), 2005)
    assert len(events) == 17
    assert events[0] == EventRef(2005, 1, "2005 Spanish motorcycle Grand Prix")


def test_2024_events_include_irregular_titles():
    events = parse_season_events(load_fixture(SEASON_2024), 2024)
    assert len(events) == 20
    assert [e.round for e in events] == list(range(1, 21))
    assert "2024 Motorcycle Grand Prix of the Americas" in {e.wiki_title for e in events}
    assert events[-1].wiki_title == "2024 Solidarity motorcycle Grand Prix"


def test_rounds_without_report_link_are_skipped():
    html = (
        '<div class="mw-parser-output"><table class="wikitable">'
        "<tr><th>Round</th><th>Grand Prix</th><th>Report</th></tr>"
        '<tr><td>1</td><td>A</td><td><a href="/wiki/2020_A_Grand_Prix">Report</a></td></tr>'
        "<tr><td>2</td><td>B (cancelled)</td><td></td></tr>"
        '<tr><td colspan="3">Source: x</td></tr>'
        "</table></div>"
    )
    assert parse_season_events(html, 2020) == [EventRef(2020, 1, "2020 A Grand Prix")]


def test_page_without_results_table_has_no_events():
    assert parse_season_events('<div class="mw-parser-output"><p>TBA</p></div>', 2030) == []
