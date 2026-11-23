from datetime import date
from pathlib import Path

import pytest

from paddock.db.loader import MissingCachedPageError, load_snapshot
from paddock.ingest.cache import HtmlCache
from paddock.ingest.manifest import Manifest, ManifestPage, PageKind
from paddock.ingest.race_parser import parse_gp_results
from tests.ingest.test_snapshot import gp_html
from tests.wiki_fixtures import (
    FIXTURES_DIR,
    MARQUEZ,
    QATAR_2024,
    SEASON_2005,
    SEASON_2024,
    SPAIN_2005,
    load_fixture,
)

pytestmark = pytest.mark.db


def make_manifest(*pages: ManifestPage, aliases: dict[str, str] | None = None) -> Manifest:
    return Manifest(
        snapshot_date=date(2026, 11, 23),
        first_season=2005,
        last_season=2024,
        pages=pages,
        rider_aliases=aliases or {},
    )


@pytest.fixture
def mini_manifest() -> Manifest:
    return make_manifest(
        ManifestPage(PageKind.SEASON, "2005 Grand Prix motorcycle racing season", SEASON_2005, season=2005),
        ManifestPage(PageKind.SEASON, "2024 MotoGP World Championship", SEASON_2024, season=2024),
        ManifestPage(PageKind.EVENT, "2005 Spanish motorcycle Grand Prix", SPAIN_2005, season=2005, round=1),
        ManifestPage(PageKind.EVENT, "2024 Qatar motorcycle Grand Prix", QATAR_2024, season=2024, round=1),
        ManifestPage(PageKind.RIDER, "Marc Márquez", MARQUEZ),
    )


@pytest.fixture
def fixture_cache() -> HtmlCache:
    return HtmlCache(FIXTURES_DIR)


def synthetic_snapshot(
    tmp_path: Path, events: dict[int, str], riders: dict[int, tuple[str, str]], aliases: dict[str, str] | None = None
) -> tuple[Manifest, HtmlCache]:
    """A one-season manifest over synthetic pages: events = revid → GP html, riders = revid → (title, html)."""
    cache = HtmlCache(tmp_path)
    cache.put(1, "<p>season</p>")
    pages = [ManifestPage(PageKind.SEASON, "2005 Grand Prix motorcycle racing season", 1, season=2005)]
    for round_no, (revid, html) in enumerate(events.items(), start=1):
        cache.put(revid, html)
        pages.append(ManifestPage(PageKind.EVENT, f"2005 GP {round_no}", revid, season=2005, round=round_no))
    for revid, (title, html) in riders.items():
        cache.put(revid, html)
        pages.append(ManifestPage(PageKind.RIDER, title, revid))
    return make_manifest(*pages, aliases=aliases), cache


def test_load_counts(db, mini_manifest, fixture_cache):
    stats = load_snapshot(db, mini_manifest, fixture_cache)
    expected = len(parse_gp_results(load_fixture(SPAIN_2005))) + len(parse_gp_results(load_fixture(QATAR_2024)))
    assert (stats.seasons, stats.events, stats.results) == (2, 2, expected)
    assert stats.riders == db.execute("SELECT count(*) FROM riders").fetchone()[0]
    assert stats.bio_sections == db.execute("SELECT count(*) FROM bio_sections").fetchone()[0] > 0


def test_retirement_is_ret_not_crash(db, mini_manifest, fixture_cache):
    load_snapshot(db, mini_manifest, fixture_cache)
    assert db.execute(
        "SELECT status FROM results JOIN riders r ON r.id = rider_id WHERE r.name = 'Nicky Hayden'"
    ).fetchone() == ("RET",)


def test_sprint_and_race_are_separate_sessions(db, mini_manifest, fixture_cache):
    load_snapshot(db, mini_manifest, fixture_cache)
    rows = db.execute(
        "SELECT session::text, position, points FROM results JOIN riders r ON r.id = rider_id "
        "WHERE r.name = 'Jorge Martín' ORDER BY session"
    ).fetchall()
    assert [(s, p) for s, p, _ in rows] == [("race", 3), ("sprint", 1)]


def test_load_merges_aliased_rider_links(db, tmp_path):  # Review Focus 1
    manifest, cache = synthetic_snapshot(
        tmp_path,
        events={10: gp_html("Dani Pedrosa"), 11: gp_html("Daniel Pedrosa")},
        riders={20: ("Dani Pedrosa", '<div class="mw-parser-output"><p>Bio.</p></div>')},
        aliases={"Daniel Pedrosa": "Dani Pedrosa"},
    )
    load_snapshot(db, manifest, cache)
    assert db.execute("SELECT name, wiki_title, revid FROM riders").fetchall() == [("Dani Pedrosa", "Dani Pedrosa", 20)]
    assert db.execute("SELECT count(*) FROM results").fetchone() == (2,)


def test_rider_without_article_is_loaded(db, tmp_path):  # Review Focus 2
    red_link = '<a href="/w/index.php?title=John_Doe&amp;action=edit&amp;redlink=1" class="new">John Doe</a>'
    html = gp_html("Placeholder").replace('<a href="/wiki/Placeholder">Placeholder</a>', red_link)
    manifest, cache = synthetic_snapshot(tmp_path, events={10: html, 11: html}, riders={})
    load_snapshot(db, manifest, cache)
    assert db.execute("SELECT name, wiki_title, revid FROM riders").fetchall() == [("John Doe", None, None)]
    assert db.execute("SELECT count(*) FROM results").fetchone() == (2,)
    assert db.execute("SELECT count(*) FROM bio_sections").fetchone() == (0,)


def test_linked_rider_without_manifest_page_keeps_title_without_bio(db, tmp_path):
    manifest, cache = synthetic_snapshot(tmp_path, events={10: gp_html("Old Rider (racer)")}, riders={})
    load_snapshot(db, manifest, cache)
    assert db.execute("SELECT name, wiki_title, revid FROM riders").fetchall() == [
        ("Old Rider", "Old Rider (racer)", None)
    ]


def test_rider_seasons_view(db, mini_manifest, fixture_cache):
    load_snapshot(db, mini_manifest, fixture_cache)
    rows = db.execute(
        "SELECT team, constructor FROM rider_seasons rs JOIN riders r ON r.id = rs.rider_id "
        "WHERE r.name = 'Francesco Bagnaia' AND season_year = 2024"
    ).fetchall()
    assert rows == [("Ducati Lenovo Team", "Ducati")]


def test_bio_sections_loaded_with_metadata(db, mini_manifest, fixture_cache):
    load_snapshot(db, mini_manifest, fixture_cache)
    row = db.execute(
        "SELECT year_from, team, source_url FROM bio_sections "
        "WHERE heading_path[array_length(heading_path, 1)] = '2014: Domination'"
    ).fetchone()
    assert row == (2014, "Repsol Honda Team", f"https://en.wikipedia.org/w/index.php?oldid={MARQUEZ}")


def test_reload_is_idempotent(db, mini_manifest, fixture_cache):
    first = load_snapshot(db, mini_manifest, fixture_cache)
    second = load_snapshot(db, mini_manifest, fixture_cache)
    assert first == second
    assert db.execute("SELECT min(id) FROM seasons JOIN events ON true").fetchone() is not None
    assert db.execute("SELECT count(*) FROM results").fetchone() == (first.results,)


def test_missing_cached_page_raises(db, mini_manifest, tmp_path):
    with pytest.raises(MissingCachedPageError, match="2005 Grand Prix motorcycle racing season"):
        load_snapshot(db, mini_manifest, HtmlCache(tmp_path))


def test_failed_load_keeps_previous_data(db, mini_manifest, fixture_cache, tmp_path):
    load_snapshot(db, mini_manifest, fixture_cache)
    with pytest.raises(MissingCachedPageError):
        load_snapshot(db, mini_manifest, HtmlCache(tmp_path))
    assert db.execute("SELECT count(*) FROM events").fetchone() == (2,)
