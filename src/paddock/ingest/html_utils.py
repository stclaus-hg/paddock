import copy
import re
from urllib.parse import parse_qs, unquote, urlsplit

from bs4 import Tag

_BRACKET_MARKER = re.compile(r"\[[^\]]*\]")
_NOISE_SELECTORS = ("sup", "span.mw-editsection", "style")
_ARTICLE_PREFIXES = ("/wiki/", "./")
_EDIT_PATH = "/w/index.php"


def cell_text(tag: Tag) -> str:
    """Visible text of a tag: footnotes and edit links removed, whitespace collapsed."""
    clean = copy.copy(tag)
    for noise in clean.select(", ".join(_NOISE_SELECTORS)):
        noise.decompose()
    for line_break in clean.find_all("br"):
        line_break.replace_with(" ")
    text = _BRACKET_MARKER.sub("", clean.get_text())
    return " ".join(text.split())


def link_target(tag: Tag) -> tuple[str | None, bool]:
    """The page title the tag links to and whether that page exists.

    Flag icons and other image links are skipped. A red link (page does not exist) gives the title it would
    have and ``False``; a tag without an article link gives ``(None, False)``.
    """
    for anchor in tag.find_all("a", href=True):
        if anchor.find_parent("span", class_="flagicon") or anchor.find("img"):
            continue
        href = str(anchor["href"])
        target = _title_from_href(href)
        if target is None:
            continue
        exists = "new" not in (anchor.get("class") or [])
        return target, exists
    return None, False


def _title_from_href(href: str) -> str | None:
    parts = urlsplit(href)
    if parts.netloc:
        return None
    if parts.path == _EDIT_PATH:
        titles = parse_qs(parts.query).get("title")
        return titles[0].replace("_", " ") if titles else None
    for prefix in _ARTICLE_PREFIXES:
        if parts.path.startswith(prefix):
            return unquote(parts.path.removeprefix(prefix)).replace("_", " ")
    return None


def expand_row(tr: Tag) -> list[Tag] | None:
    """The row's cells with each ``colspan`` cell repeated once per column it covers.

    Returns ``None`` for a row made of a single cell (a full-width footer such as "Sources: …").
    """
    cells = tr.find_all(["th", "td"], recursive=False)
    if len(cells) <= 1:
        return None
    expanded: list[Tag] = []
    for cell in cells:
        span = str(cell.get("colspan", "1"))
        expanded.extend([cell] * (int(span) if span.isdigit() else 1))
    return expanded
