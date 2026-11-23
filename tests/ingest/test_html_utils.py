from bs4 import BeautifulSoup, Tag

from paddock.ingest.html_utils import cell_text, expand_row


def first_row(html: str) -> Tag:
    tr = BeautifulSoup(f"<table>{html}</table>", "lxml").find("tr")
    assert isinstance(tr, Tag)
    return tr


def test_expand_row_repeats_colspan_cells():
    tr = first_row('<tr><td>8</td><td colspan="2">No race</td><td>Report</td></tr>')
    assert [cell_text(c) for c in expand_row(tr)] == ["8", "No race", "No race", "Report"]


def test_expand_row_returns_none_for_full_width_footer():
    assert expand_row(first_row('<tr><th colspan="9">Sources: [1]</th></tr>')) is None


def test_expand_row_ignores_bad_colspan():
    tr = first_row('<tr><td colspan="x">a</td><td>b</td></tr>')
    assert [cell_text(c) for c in expand_row(tr)] == ["a", "b"]
