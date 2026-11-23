"""Download Wikipedia pages as test fixtures.

Usage: uv run python scripts/fetch_fixture.py <revid-or-title> [...]

An integer argument is fetched by revision id; anything else is treated as a page title, resolved to its
latest revision first. Each page is written to tests/fixtures/wiki/<revid>.html.
"""

import sys
from pathlib import Path

from paddock.ingest.cache import HtmlCache
from paddock.ingest.wiki_client import WikiClient, make_http_client

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "wiki"


def main(args: list[str]) -> int:
    if not args:
        print(__doc__)
        return 2
    cache = HtmlCache(FIXTURES_DIR)
    with make_http_client() as http:
        client = WikiClient(http)
        for arg in args:
            if arg.isdigit():
                revid = int(arg)
            else:
                found = client.latest_revisions([arg])[arg].revid
                if found is None:
                    print(f"missing page: {arg}")
                    return 1
                revid = found
            cache.put(revid, client.fetch_html(revid))
            print(f"{revid}\t{arg}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
