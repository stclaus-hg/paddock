from collections.abc import Sequence
from datetime import date

import pytest

from paddock.ingest.cache import HtmlCache
from paddock.ingest.manifest import Manifest, ManifestPage, PageKind, read_manifest, write_manifest
from paddock.ingest.race_parser import parse_gp_results
from paddock.ingest.snapshot import IncompleteSeasonError, SnapshotError, build_snapshot, ensure_cached
from paddock.ingest.wiki_client import PageRevision
from tests.wiki_fixtures import SPAIN_2005, load_fixture

BIO_HTML = '<div class="mw-parser-output"><p>A rider.</p></div>'
NO_RESULTS_HTML = '<div class="mw-parser-output"><p>The race will be held later.</p></div>'


class FakeWikiClient:
    """In-memory stand-in for WikiClient: title → (canonical title, revid) and revid → HTML."""

    def __init__(self) -> None:
        self.pages: dict[str, tuple[str, int]] = {}
        self.html: dict[int, str] = {}
        self.fetched: list[int] = []
        self._next_revid = 1

    def add(self, title: str, html: str, revid: int | None = None) -> int:
        revid = revid if revid is not None else self._new_revid()
        self.pages[title] = (title, revid)
        self.html[revid] = html
        return revid

    def redirect(self, source: str, target: str) -> None:
        self.pages[source] = self.pages[target][0], self.pages[target][1]

    def _new_revid(self) -> int:
        self._next_revid += 1
        return self._next_revid

    def latest_revisions(self, titles: Sequence[str]) -> dict[str, PageRevision]:
        result = {}
        for title in titles:
            canonical, revid = self.pages.get(title, (title, None))
            result[title] = PageRevision(title, canonical, revid)
        return result

    def fetch_html(self, revid: int) -> str:
        self.fetched.append(revid)
        return self.html[revid]


def season_html(*events: str) -> str:
    rows = "".join(
        f'<tr><td>{i}</td><td>GP</td><td><a href="/wiki/{t.replace(" ", "_")}">Report</a></td></tr>'
        for i, t in enumerate(events, start=1)
    )
    return (
        '<div class="mw-parser-output"><table class="wikitable">'
        f"<tr><th>Round</th><th>Grand Prix</th><th>Report</th></tr>{rows}</table></div>"
    )


def gp_html(*rider_links: str) -> str:
    rows = "".join(
        f'<tr><th>{i}</th><td>{i}</td><td><a href="/wiki/{link.replace(" ", "_")}">{link}</a></td><td>T</td>'
        f"<td>Honda</td><td>20</td><td>+1</td><td>{i}</td><td>1</td></tr>"
        for i, link in enumerate(rider_links, start=1)
    )
    return (
        '<div class="mw-parser-output"><div class="mw-heading mw-heading2"><h2>MotoGP classification</h2></div>'
        '<table class="wikitable"><tr><th>Pos.</th><th>No.</th><th>Rider</th><th>Team</th><th>Constructor</th>'
        f"<th>Laps</th><th>Time/Retired</th><th>Grid</th><th>Points</th></tr>{rows}</table></div>"
    )


def add_complete_2005(fake: FakeWikiClient) -> None:
    fake.add("2005 Grand Prix motorcycle racing season", season_html("2005 Spanish motorcycle Grand Prix"))
    spain = load_fixture(SPAIN_2005)
    fake.add("2005 Spanish motorcycle Grand Prix", spain, revid=SPAIN_2005)
    for row in parse_gp_results(spain):
        assert row.rider_link is not None
        fake.add(row.rider_link, BIO_HTML)


@pytest.fixture
def cache(tmp_path) -> HtmlCache:
    return HtmlCache(tmp_path / "raw")


def test_manifest_roundtrip(tmp_path):
    manifest = Manifest(
        snapshot_date=date(2026, 11, 23),
        first_season=2002,
        last_season=2025,
        pages=(
            ManifestPage(PageKind.SEASON, "2025 MotoGP World Championship", 10, season=2025),
            ManifestPage(PageKind.EVENT, "2025 Thai motorcycle Grand Prix", 11, season=2025, round=1),
            ManifestPage(PageKind.RIDER, "Marc Márquez", 12),
        ),
        rider_aliases={"Daniel Pedrosa": "Dani Pedrosa"},
    )
    path = tmp_path / "snapshot" / "manifest.json"
    write_manifest(manifest, path)
    assert read_manifest(path) == manifest
    assert "Márquez" in path.read_text(encoding="utf-8")  # human-readable, not \u-escaped
    assert not list(path.parent.glob("*.tmp"))


def test_snapshot_collects_seasons_events_and_riders(cache):
    fake = FakeWikiClient()
    add_complete_2005(fake)

    manifest = build_snapshot(fake, cache, today=date(2006, 1, 10), first_season=2005)

    assert (manifest.first_season, manifest.last_season, manifest.snapshot_date) == (2005, 2005, date(2006, 1, 10))
    assert {p.kind for p in manifest.pages} == {PageKind.SEASON, PageKind.EVENT, PageKind.RIDER}
    assert sum(p.kind is PageKind.RIDER for p in manifest.pages) == 21
    event = next(p for p in manifest.pages if p.kind is PageKind.EVENT)
    assert (event.title, event.revid, event.season, event.round) == (
        "2005 Spanish motorcycle Grand Prix",
        SPAIN_2005,
        2005,
        1,
    )
    assert all(cache.has(p.revid) for p in manifest.pages)


def test_snapshot_uses_cache_instead_of_refetching(cache):
    fake = FakeWikiClient()
    add_complete_2005(fake)
    build_snapshot(fake, cache, today=date(2006, 1, 10), first_season=2005)
    fake.fetched.clear()

    build_snapshot(fake, cache, today=date(2006, 1, 10), first_season=2005)

    assert fake.fetched == []


def test_current_season_without_results_is_excluded(cache):
    fake = FakeWikiClient()
    add_complete_2005(fake)
    fake.add("2006 Grand Prix motorcycle racing season", season_html("2006 Future motorcycle Grand Prix"))
    fake.add("2006 Future motorcycle Grand Prix", NO_RESULTS_HTML)

    manifest = build_snapshot(fake, cache, today=date(2006, 5, 1), first_season=2005)

    assert manifest.last_season == 2005
    assert not any(p.season == 2006 for p in manifest.pages)


def test_incomplete_past_season_raises_with_page_title(cache):  # Review Focus 5
    fake = FakeWikiClient()
    add_complete_2005(fake)
    fake.add("2006 Grand Prix motorcycle racing season", season_html("2006 Broken motorcycle Grand Prix"))
    fake.add("2006 Broken motorcycle Grand Prix", NO_RESULTS_HTML)

    with pytest.raises(IncompleteSeasonError) as err:
        build_snapshot(fake, cache, today=date(2007, 1, 1), first_season=2005)

    assert err.value.season == 2006
    assert "2006 Broken motorcycle Grand Prix" in err.value.titles


def test_past_season_with_missing_event_page_raises(cache):
    fake = FakeWikiClient()
    add_complete_2005(fake)
    fake.add("2006 Grand Prix motorcycle racing season", season_html("2006 Deleted motorcycle Grand Prix"))

    with pytest.raises(IncompleteSeasonError) as err:
        build_snapshot(fake, cache, today=date(2007, 1, 1), first_season=2005)

    assert err.value.titles == ["2006 Deleted motorcycle Grand Prix"]


def test_past_season_page_without_calendar_raises(cache):
    fake = FakeWikiClient()
    add_complete_2005(fake)
    fake.add("2006 Grand Prix motorcycle racing season", NO_RESULTS_HTML)

    with pytest.raises(IncompleteSeasonError) as err:
        build_snapshot(fake, cache, today=date(2007, 1, 1), first_season=2005)

    assert err.value.titles == ["2006 Grand Prix motorcycle racing season"]


def test_no_complete_season_is_an_error(cache):
    with pytest.raises(SnapshotError):
        build_snapshot(FakeWikiClient(), cache, today=date(2006, 1, 10), first_season=2005)


def test_snapshot_maps_redirected_rider_links_to_one_canonical_title(cache):  # Review Focus 1
    fake = FakeWikiClient()
    fake.add(
        "2005 Grand Prix motorcycle racing season",
        season_html("2005 A motorcycle Grand Prix", "2005 B motorcycle Grand Prix"),
    )
    fake.add("2005 A motorcycle Grand Prix", gp_html("Dani Pedrosa"))
    fake.add("2005 B motorcycle Grand Prix", gp_html("Daniel Pedrosa"))
    fake.add("Dani Pedrosa", BIO_HTML)
    fake.redirect("Daniel Pedrosa", "Dani Pedrosa")

    manifest = build_snapshot(fake, cache, today=date(2006, 1, 10), first_season=2005)

    assert manifest.rider_aliases == {"Daniel Pedrosa": "Dani Pedrosa"}
    assert sum(p.title == "Dani Pedrosa" for p in manifest.pages) == 1


def test_ensure_cached_fetches_only_missing(cache):
    fake = FakeWikiClient()
    revids = [fake.add(f"Page {i}", f"<p>{i}</p>") for i in range(3)]
    cache.put(revids[0], "<p>0</p>")
    manifest = Manifest(
        snapshot_date=date(2026, 1, 1),
        first_season=2025,
        last_season=2025,
        pages=tuple(ManifestPage(PageKind.RIDER, f"Page {i}", r) for i, r in enumerate(revids)),
        rider_aliases={},
    )

    assert ensure_cached(manifest, fake, cache) == 2
    assert sorted(fake.fetched) == sorted(revids[1:])
    assert all(cache.has(r) for r in revids)


def test_known_cancelled_race_is_kept_without_error(cache):
    fake = FakeWikiClient()
    fake.add(
        "2011 Grand Prix motorcycle racing season",
        season_html("2011 A motorcycle Grand Prix", "2011 Malaysian motorcycle Grand Prix"),
    )
    fake.add("2011 A motorcycle Grand Prix", gp_html("Rider A"))
    fake.add("2011 Malaysian motorcycle Grand Prix", NO_RESULTS_HTML)
    fake.add("Rider A", BIO_HTML)

    manifest = build_snapshot(fake, cache, today=date(2012, 1, 10), first_season=2011)

    events = [(p.title, p.round) for p in manifest.pages if p.kind is PageKind.EVENT]
    assert events == [("2011 A motorcycle Grand Prix", 1), ("2011 Malaysian motorcycle Grand Prix", 2)]
