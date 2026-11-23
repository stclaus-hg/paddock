"""Wikipedia pages saved as test fixtures (see tests/fixtures/wiki/README.md)."""

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "wiki"

#: Wikipedia revision ids of the pages saved in tests/fixtures/wiki (see its README).
SPAIN_2005 = 1367354866
QATAR_2024 = 1377682352
SEASON_2003 = 1373574739
SEASON_2005 = 1383846918
SEASON_2024 = 1386901932
MARQUEZ = 1387261184


def load_fixture(revid: int) -> str:
    return (FIXTURES_DIR / f"{revid}.html").read_text(encoding="utf-8")
