"""The pinned snapshot: which Wikipedia page revisions the database is built from."""

import json
import os
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

JSON_INDENT = 2


class PageKind(StrEnum):
    SEASON = "season"
    EVENT = "event"
    RIDER = "rider"


@dataclass(frozen=True)
class ManifestPage:
    kind: PageKind
    title: str
    revid: int
    season: int | None = None
    round: int | None = None


@dataclass(frozen=True)
class Manifest:
    snapshot_date: date
    first_season: int
    last_season: int
    pages: tuple[ManifestPage, ...]
    rider_aliases: dict[str, str]  #: rider link title as written on a results page → canonical article title


def read_manifest(path: Path) -> Manifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Manifest(
        snapshot_date=date.fromisoformat(data["snapshot_date"]),
        first_season=data["first_season"],
        last_season=data["last_season"],
        pages=tuple(
            ManifestPage(
                kind=PageKind(p["kind"]), title=p["title"], revid=p["revid"], season=p["season"], round=p["round"]
            )
            for p in data["pages"]
        ),
        rider_aliases=data["rider_aliases"],
    )


def write_manifest(manifest: Manifest, path: Path) -> None:
    """Write the manifest atomically: readers see either the old file or the complete new one."""
    data: dict[str, Any] = {
        "snapshot_date": manifest.snapshot_date.isoformat(),
        "first_season": manifest.first_season,
        "last_season": manifest.last_season,
        "pages": [
            {"kind": p.kind.value, "title": p.title, "revid": p.revid, "season": p.season, "round": p.round}
            for p in manifest.pages
        ],
        "rider_aliases": manifest.rider_aliases,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=JSON_INDENT, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
