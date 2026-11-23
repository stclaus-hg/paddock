"""Rider article → prose sections with year and team metadata taken from their headings."""

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

from paddock.ingest.html_utils import cell_text
from paddock.models import BioSection

#: top-level sections that hold no biography prose (or only tables and links)
EXCLUDED_SECTIONS = frozenset(
    {
        "References",
        "Notes",
        "External links",
        "See also",
        "Further reading",
        "Bibliography",
        "Career statistics",
        "Footnotes",
        "Citations",
        "Sources",
    }
)
HEADING_TAGS = ("h2", "h3", "h4", "h5", "h6")
PROSE_TAGS = ("p",)
LIST_TAGS = ("ul", "ol")
PARAGRAPH_SEPARATOR = "\n\n"
LIST_ITEM_PREFIX = "- "

_YEARS = r"(?P<year_from>\d{4})(?:\s*(?P<dash>[–-])\s*(?P<year_to>\d{4})?)?"
_YEAR_HEADING = re.compile(rf"^{_YEARS}\s*(?::.*)?$")  # "2014: Domination", "2008", "2015–2016: Struggles"
_TEAM_HEADING = re.compile(rf"^(?P<team>.+?)\s*\({_YEARS}\)$")  # "Repsol Honda Team (2013–2023)"


@dataclass(frozen=True)
class HeadingMeta:
    year_from: int | None
    year_to: int | None  #: None for an open range such as "(2025–)"
    team: str | None


NO_META = HeadingMeta(None, None, None)


def parse_heading_meta(heading: str) -> HeadingMeta:
    match = _YEAR_HEADING.match(heading) or _TEAM_HEADING.match(heading)
    if match is None:
        return NO_META
    year_from = int(match["year_from"])
    if match["year_to"] is not None:
        year_to: int | None = int(match["year_to"])
    else:
        year_to = None if match["dash"] else year_from
    team = match.groupdict().get("team")
    return HeadingMeta(year_from, year_to, team)


@dataclass
class _Heading:
    level: int
    title: str
    meta: HeadingMeta


@dataclass
class _Section:
    headings: list[_Heading]
    blocks: list[str] = field(default_factory=list)

    @property
    def path(self) -> tuple[str, ...]:
        return tuple(h.title for h in self.headings)

    def meta(self) -> HeadingMeta:
        """Own heading's metadata; each missing field comes from the nearest ancestor that has it."""
        year_from = year_to = team = None
        for heading in reversed(self.headings):
            year_from = year_from if year_from is not None else heading.meta.year_from
            team = team if team is not None else heading.meta.team
        for heading in reversed(self.headings):
            if heading.meta.year_from is not None:
                year_to = heading.meta.year_to
                break
        return HeadingMeta(year_from, year_to, team)


def parse_bio(html: str) -> list[BioSection]:
    root = BeautifulSoup(html, "lxml").select_one("div.mw-parser-output")
    if root is None:
        return []
    sections: list[BioSection] = []
    current = _Section(headings=[])
    for child in root.find_all(recursive=False):
        heading = _heading_of(child)
        if heading is not None:
            _flush(current, sections)
            parents = [h for h in current.headings if h.level < heading.level]
            current = _Section(headings=[*parents, heading])
        elif child.name in PROSE_TAGS:
            current.blocks.append(cell_text(child))
        elif child.name in LIST_TAGS:
            items = [cell_text(li) for li in child.find_all("li", recursive=False)]
            current.blocks.append("\n".join(f"{LIST_ITEM_PREFIX}{item}" for item in items if item))
    _flush(current, sections)
    return sections


def _heading_of(tag: Tag) -> _Heading | None:
    if tag.name == "div" and "mw-heading" in (tag.get("class") or []):
        inner = tag.find(HEADING_TAGS)
        if not isinstance(inner, Tag):
            return None
        tag = inner
    if tag.name not in HEADING_TAGS:
        return None
    title = cell_text(tag)
    return _Heading(level=int(tag.name[1]), title=title, meta=parse_heading_meta(title))


def _flush(section: _Section, sections: list[BioSection]) -> None:
    text = PARAGRAPH_SEPARATOR.join(block for block in section.blocks if block)
    if not text or (section.headings and section.headings[0].title in EXCLUDED_SECTIONS):
        return
    meta = section.meta()
    sections.append(
        BioSection(
            ordinal=len(sections),
            heading_path=section.path,
            text=text,
            year_from=meta.year_from,
            year_to=meta.year_to,
            team=meta.team,
        )
    )
