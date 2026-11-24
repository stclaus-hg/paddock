"""`paddock ingest snapshot|fetch|load` — build the knowledge base from Wikipedia."""

import argparse
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

import structlog

from paddock.config import Settings, load_settings
from paddock.db.connection import apply_schema, connect
from paddock.db.loader import MissingCachedPageError, load_snapshot
from paddock.ingest.cache import HtmlCache
from paddock.ingest.manifest import read_manifest, write_manifest
from paddock.ingest.snapshot import SnapshotError, build_snapshot, ensure_cached
from paddock.ingest.wiki_client import WikiClient, WikiRequestError, make_http_client
from paddock.logging import configure_logging

EXIT_OK = 0
EXIT_FAILURE = 1

log = structlog.get_logger()

Command = Callable[[Settings], int]


def snapshot(settings: Settings) -> int:
    """Discover and pin pages, cache their HTML, then write the manifest — only if everything succeeded."""
    with make_http_client() as http:
        try:
            manifest = build_snapshot(WikiClient(http), HtmlCache(settings.cache_dir), today=datetime.now(UTC).date())
        except (SnapshotError, WikiRequestError) as exc:
            log.error("snapshot.failed", error=str(exc))
            return EXIT_FAILURE
    write_manifest(manifest, settings.manifest_path)
    log.info(
        "snapshot.written",
        path=str(settings.manifest_path),
        first_season=manifest.first_season,
        last_season=manifest.last_season,
        pages=len(manifest.pages),
        rider_aliases=len(manifest.rider_aliases),
    )
    return EXIT_OK


def fetch(settings: Settings) -> int:
    """Download any page of the committed manifest that is missing from the local cache."""
    manifest = read_manifest(settings.manifest_path)
    with make_http_client() as http:
        try:
            fetched = ensure_cached(manifest, WikiClient(http), HtmlCache(settings.cache_dir))
        except WikiRequestError as exc:
            log.error("fetch.failed", error=str(exc))
            return EXIT_FAILURE
    log.info("fetch.done", fetched=fetched, pages=len(manifest.pages))
    return EXIT_OK


def load(settings: Settings) -> int:
    """Rebuild the database from the manifest and the cache."""
    manifest = read_manifest(settings.manifest_path)
    with connect(settings.database_url) as conn:
        apply_schema(conn)
        try:
            load_snapshot(conn, manifest, HtmlCache(settings.cache_dir))
        except MissingCachedPageError as exc:
            log.error("load.failed", error=str(exc))
            return EXIT_FAILURE
    return EXIT_OK


COMMANDS: dict[str, Command] = {"snapshot": snapshot, "fetch": fetch, "load": load}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paddock")
    groups = parser.add_subparsers(dest="group", required=True)
    ingest = groups.add_parser("ingest", help="build the knowledge base from Wikipedia")
    ingest.add_argument("command", choices=COMMANDS, help="snapshot: pin pages; fetch: fill cache; load: rebuild DB")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # argparse exits on bad usage and on --help
        return exc.code if isinstance(exc.code, int) else EXIT_FAILURE
    return COMMANDS[args.command](load_settings())
