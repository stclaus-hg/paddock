"""Discover the pages of every completed season and pin them to their current revisions."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import structlog

from paddock.ingest.cache import HtmlCache
from paddock.ingest.manifest import Manifest, ManifestPage, PageKind
from paddock.ingest.race_parser import parse_gp_results
from paddock.ingest.season_parser import parse_season_events, season_page_title
from paddock.ingest.wiki_client import PageRevision
from paddock.models import SessionType

FIRST_SEASON = 2002  #: first season of the four-stroke MotoGP era; earlier years are out of scope

#: Grand Prix whose MotoGP race was not held (no classification exists); kept in the calendar without results.
CANCELLED_RACES = frozenset(
    {
        "2011 Malaysian motorcycle Grand Prix",  # stopped after Marco Simoncelli's fatal accident
        "2018 British motorcycle Grand Prix",  # cancelled because of standing water on the track
    }
)

log = structlog.get_logger()


class WikiSource(Protocol):
    def latest_revisions(self, titles: Sequence[str]) -> dict[str, PageRevision]: ...

    def fetch_html(self, revid: int) -> str: ...


class SnapshotError(Exception):
    """The snapshot cannot be built."""


class IncompleteSeasonError(SnapshotError):
    """A finished season has Grand Prix pages without a MotoGP race classification."""

    def __init__(self, season: int, titles: list[str]) -> None:
        super().__init__(f"Season {season} is incomplete; check these pages: {', '.join(titles)}")
        self.season = season
        self.titles = titles


@dataclass
class _SeasonPages:
    pages: list[ManifestPage] = field(default_factory=list)
    rider_links: set[str] = field(default_factory=set)
    problems: list[str] = field(default_factory=list)


def build_snapshot(client: WikiSource, cache: HtmlCache, today: date, first_season: int = FIRST_SEASON) -> Manifest:
    """Pin every complete season from ``first_season`` on, plus all linked rider articles.

    The current (or a future) season is left out when it is not complete yet; an incomplete past season
    raises ``IncompleteSeasonError``. Nothing is written to the manifest file here.
    """
    pages: list[ManifestPage] = []
    rider_links: set[str] = set()
    last_season: int | None = None
    for year in range(first_season, today.year + 1):
        season = _collect_season(client, cache, year)
        if season is None:
            if year < today.year:
                raise SnapshotError(f"No Wikipedia article for past season {year}: {season_page_title(year)!r}")
            break
        if season.problems:
            if year >= today.year:
                log.info("snapshot.season_excluded", season=year, incomplete=len(season.problems))
                break
            raise IncompleteSeasonError(year, season.problems)
        pages.extend(season.pages)
        rider_links |= season.rider_links
        last_season = year
        log.info("snapshot.season", season=year, events=len(season.pages) - 1)
    if last_season is None:
        raise SnapshotError(f"No complete season found from {first_season} to {today.year}")

    rider_pages, aliases = _collect_riders(client, cache, rider_links)
    return Manifest(
        snapshot_date=today,
        first_season=first_season,
        last_season=last_season,
        pages=tuple(pages + rider_pages),
        rider_aliases=aliases,
    )


def ensure_cached(manifest: Manifest, client: WikiSource, cache: HtmlCache) -> int:
    """Download every manifest page missing from the cache; returns how many were fetched."""
    fetched = 0
    for page in manifest.pages:
        if not cache.has(page.revid):
            cache.put(page.revid, client.fetch_html(page.revid))
            fetched += 1
    return fetched


def _collect_season(client: WikiSource, cache: HtmlCache, year: int) -> _SeasonPages | None:
    """The season's pages, or None when Wikipedia has no article for that season."""
    title = season_page_title(year)
    revision = client.latest_revisions([title])[title]
    if revision.revid is None:
        return None
    result = _SeasonPages(pages=[ManifestPage(PageKind.SEASON, revision.canonical_title, revision.revid, year)])
    events = parse_season_events(_html(client, cache, revision.revid), year)
    if not events:
        result.problems.append(revision.canonical_title)
        return result
    event_revisions = client.latest_revisions([e.wiki_title for e in events])
    for event in events:
        event_revision = event_revisions[event.wiki_title]
        if event_revision.revid is None:
            result.problems.append(event.wiki_title)
            continue
        rows = parse_gp_results(_html(client, cache, event_revision.revid))
        has_race = any(r.session is SessionType.RACE for r in rows)
        if not has_race and event_revision.canonical_title not in CANCELLED_RACES:
            result.problems.append(event.wiki_title)
            continue
        result.pages.append(
            ManifestPage(PageKind.EVENT, event_revision.canonical_title, event_revision.revid, year, event.round)
        )
        result.rider_links |= {r.rider_link for r in rows if r.rider_has_article and r.rider_link}
    return result


def _collect_riders(client: WikiSource, cache: HtmlCache, links: set[str]) -> tuple[list[ManifestPage], dict[str, str]]:
    revisions = client.latest_revisions(sorted(links))
    canonical: dict[str, int] = {}
    aliases: dict[str, str] = {}
    for link, revision in revisions.items():
        if revision.revid is None:
            log.warning("snapshot.rider_page_missing", link=link)
            continue
        canonical[revision.canonical_title] = revision.revid
        if revision.canonical_title != link:
            aliases[link] = revision.canonical_title
    for revid in canonical.values():
        _html(client, cache, revid)
    log.info("snapshot.riders", riders=len(canonical), aliases=len(aliases))
    pages = [ManifestPage(PageKind.RIDER, title, revid) for title, revid in sorted(canonical.items())]
    return pages, aliases


def _html(client: WikiSource, cache: HtmlCache, revid: int) -> str:
    html = cache.get(revid)
    if html is None:
        html = client.fetch_html(revid)
        cache.put(revid, html)
    return html
