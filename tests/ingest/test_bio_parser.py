import re

import pytest

from paddock.ingest.bio_parser import HeadingMeta, parse_bio, parse_heading_meta
from tests.wiki_fixtures import MARQUEZ, load_fixture


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("2014: Domination", HeadingMeta(2014, 2014, None)),
        ("2008", HeadingMeta(2008, 2008, None)),
        ("Repsol Honda Team (2013–2023)", HeadingMeta(2013, 2023, "Repsol Honda Team")),
        ("Ducati Lenovo Team (2025–)", HeadingMeta(2025, None, "Ducati Lenovo Team")),
        ("Gresini Racing MotoGP (2024)", HeadingMeta(2024, 2024, "Gresini Racing MotoGP")),
        ("2015–2016: Struggles", HeadingMeta(2015, 2016, None)),
        ("2015-2016: Struggles", HeadingMeta(2015, 2016, None)),
        ("Team X (2010-2012)", HeadingMeta(2010, 2012, "Team X")),
        ("125cc World Championship", HeadingMeta(None, None, None)),
        ("Early life", HeadingMeta(None, None, None)),
    ],
)
def test_parse_heading_meta(heading, expected):
    assert parse_heading_meta(heading) == expected


def test_marquez_sections():
    sections = parse_bio(load_fixture(MARQUEZ))
    assert sections[0].heading_path == ()
    assert "Márquez" in sections[0].text
    domination = next(s for s in sections if s.heading_path[-1:] == ("2014: Domination",))
    assert (domination.year_from, domination.year_to, domination.team) == (2014, 2014, "Repsol Honda Team")
    assert domination.heading_path == (
        "Career",
        "MotoGP World Championship",
        "Repsol Honda Team (2013–2023)",
        "2014: Domination",
    )
    assert not any(s.heading_path and s.heading_path[0] == "References" for s in sections)
    assert not any(re.search(r"\[\d+\]", s.text) for s in sections)  # citation markers removed
    assert [s.ordinal for s in sections] == list(range(len(sections)))


def page(body: str) -> str:
    return f'<div class="mw-parser-output">{body}</div>'


def h(level: int, text: str) -> str:
    return f'<div class="mw-heading mw-heading{level}"><h{level}>{text}</h{level}></div>'


def test_only_prose_and_lists_are_collected():
    html = page(
        '<div class="shortdescription">Spanish rider</div><p>Lead text.</p>'
        '<table class="infobox"><tr><td>Born 1993</td></tr></table>'
        + h(2, "Career")
        + "<p>First.</p><ul><li>Item one</li><li>Item two</li></ul>"
        '<figure><figcaption>Caption</figcaption></figure><style>.x{}</style><p class="mw-empty-elt"></p>'
    )
    lead, career = parse_bio(html)
    assert lead.text == "Lead text."
    assert career.text == "First.\n\n- Item one\n- Item two"


def test_excluded_and_empty_sections_are_dropped():
    html = page(
        "<p>Lead.</p>"
        + h(2, "Career")
        + h(3, "Empty subsection")
        + h(3, "Full subsection")
        + "<p>Body.</p>"
        + h(2, "Career statistics")
        + "<p>Numbers.</p>"
        + h(3, "By season")
        + "<p>More numbers.</p>"
        + h(2, "References")
        + "<ol><li>Ref</li></ol>"
    )
    sections = parse_bio(html)
    assert [s.heading_path for s in sections] == [(), ("Career", "Full subsection")]
    assert [s.ordinal for s in sections] == [0, 1]


def test_metadata_is_inherited_field_by_field():
    html = page(h(2, "Team X (2010–2012)") + h(3, "2011: Good year") + "<p>Won.</p>" + h(2, "Later") + "<p>x</p>")
    good_year, later = parse_bio(html)
    assert (good_year.year_from, good_year.year_to, good_year.team) == (2011, 2011, "Team X")
    assert (later.year_from, later.year_to, later.team) == (None, None, None)


def test_page_without_content_root_has_no_sections():
    assert parse_bio("<html><body><p>x</p></body></html>") == []
