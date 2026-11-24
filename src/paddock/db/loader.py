"""Rebuild the structured store from a manifest and the cached pages it pins."""

import re
from dataclasses import dataclass

import psycopg
import structlog

from paddock.ingest.bio_parser import parse_bio
from paddock.ingest.cache import HtmlCache
from paddock.ingest.manifest import Manifest, ManifestPage, PageKind
from paddock.ingest.race_parser import parse_gp_results
from paddock.models import ResultRow

SOURCE_URL_TEMPLATE = "https://en.wikipedia.org/w/index.php?oldid={revid}"
#: "John Hopkins (motorcycle racer)" → "John Hopkins"
_DISAMBIGUATION = re.compile(r"\s*\([^)]*\)$")

log = structlog.get_logger()


class MissingCachedPageError(Exception):
    def __init__(self, revid: int, title: str) -> None:
        super().__init__(f"Page {title!r} (revision {revid}) is not in the cache; run `paddock ingest fetch`")
        self.revid = revid
        self.title = title


@dataclass(frozen=True)
class LoadStats:
    seasons: int
    events: int
    riders: int
    results: int
    bio_sections: int


def load_snapshot(conn: psycopg.Connection, manifest: Manifest, cache: HtmlCache) -> LoadStats:
    """Replace every table's contents with the snapshot, in one transaction.

    Any failure rolls back, so the database keeps its previous contents.
    """
    html = _read_all(manifest, cache)
    with conn.transaction():
        conn.execute("TRUNCATE bio_sections, results, riders, events, seasons RESTART IDENTITY CASCADE")
        loader = _Loader(conn, manifest)
        for page in manifest.pages:
            if page.kind is PageKind.SEASON:
                loader.add_season(page)
        for page in manifest.pages:
            if page.kind is PageKind.EVENT:
                loader.add_event(page, html[page.revid])
        for page in manifest.pages:
            if page.kind is PageKind.RIDER:
                loader.add_bio(page, html[page.revid])
    stats = loader.stats()
    log.info("load.done", **stats.__dict__)
    return stats


def _read_all(manifest: Manifest, cache: HtmlCache) -> dict[int, str]:
    pages: dict[int, str] = {}
    for page in manifest.pages:
        html = cache.get(page.revid)
        if html is None:
            raise MissingCachedPageError(page.revid, page.title)
        pages[page.revid] = html
    return pages


class _Loader:
    def __init__(self, conn: psycopg.Connection, manifest: Manifest) -> None:
        self._conn = conn
        self._aliases = manifest.rider_aliases
        self._rider_pages = {p.title: p for p in manifest.pages if p.kind is PageKind.RIDER}
        self._riders_by_title: dict[str, int] = {}
        self._riders_by_name: dict[str, int] = {}  # riders without an article
        self._counts = {"seasons": 0, "events": 0, "results": 0, "bio_sections": 0}

    def add_season(self, page: ManifestPage) -> None:
        self._conn.execute(
            "INSERT INTO seasons (year, wiki_title, revid) VALUES (%s, %s, %s)", (page.season, page.title, page.revid)
        )
        self._counts["seasons"] += 1

    def add_event(self, page: ManifestPage, html: str) -> None:
        event_id = _returned_id(
            self._conn.execute(
                "INSERT INTO events (season_year, round, wiki_title, revid) VALUES (%s, %s, %s, %s) RETURNING id",
                (page.season, page.round, page.title, page.revid),
            )
        )
        self._counts["events"] += 1
        results = parse_gp_results(html)
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO results (event_id, rider_id, session, position, status, grid, points, laps, team,"
                " constructor, bike_number) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        event_id,
                        self._rider_id(r),
                        r.session.value,
                        r.position,
                        r.status.value,
                        r.grid,
                        r.points,
                        r.laps,
                        r.team,
                        r.constructor,
                        r.bike_number,
                    )
                    for r in results
                ],
            )
        self._counts["results"] += len(results)

    def add_bio(self, page: ManifestPage, html: str) -> None:
        rider_id = self._riders_by_title.get(page.title)
        if rider_id is None:
            rider_id = self._insert_rider(_display_name(page.title), page.title, page.revid)
            self._riders_by_title[page.title] = rider_id
        sections = parse_bio(html)
        source_url = SOURCE_URL_TEMPLATE.format(revid=page.revid)
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO bio_sections (rider_id, ordinal, heading_path, text, year_from, year_to, team,"
                " source_url) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (rider_id, s.ordinal, list(s.heading_path), s.text, s.year_from, s.year_to, s.team, source_url)
                    for s in sections
                ],
            )
        self._counts["bio_sections"] += len(sections)

    def _rider_id(self, row: ResultRow) -> int:
        if row.rider_has_article and row.rider_link:
            title = self._aliases.get(row.rider_link, row.rider_link)
            rider_id = self._riders_by_title.get(title)
            if rider_id is None:
                page = self._rider_pages.get(title)
                rider_id = self._insert_rider(_display_name(title), title, page.revid if page else None)
                self._riders_by_title[title] = rider_id
            return rider_id
        rider_id = self._riders_by_name.get(row.rider_name)
        if rider_id is None:
            rider_id = self._insert_rider(row.rider_name, None, None)
            self._riders_by_name[row.rider_name] = rider_id
        return rider_id

    def _insert_rider(self, name: str, wiki_title: str | None, revid: int | None) -> int:
        return _returned_id(
            self._conn.execute(
                "INSERT INTO riders (name, wiki_title, revid) VALUES (%s, %s, %s) RETURNING id",
                (name, wiki_title, revid),
            )
        )

    def stats(self) -> LoadStats:
        riders = len(self._riders_by_title) + len(self._riders_by_name)
        return LoadStats(riders=riders, **self._counts)


def _returned_id(cursor: psycopg.Cursor[tuple[int]]) -> int:
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("INSERT ... RETURNING id returned no row")
    return row[0]


def _display_name(title: str) -> str:
    return _DISAMBIGUATION.sub("", title)
