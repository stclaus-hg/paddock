from collections.abc import Callable

import httpx
import pytest

from paddock.ingest.cache import HtmlCache
from paddock.ingest.wiki_client import (
    MAX_ATTEMPTS,
    USER_AGENT,
    PageRevision,
    WikiClient,
    WikiRequestError,
    make_http_client,
)

Handler = Callable[[httpx.Request], httpx.Response]


def make_client(handler: Handler, sleeps: list[float] | None = None) -> WikiClient:
    http = make_http_client(transport=httpx.MockTransport(handler))
    recorded = sleeps if sleeps is not None else []
    return WikiClient(http, request_interval_s=0, sleep=recorded.append)


def test_latest_revisions_follows_redirects_and_marks_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "query": {
                    "normalized": [{"from": "dani Pedrosa (racer)", "to": "Dani Pedrosa (racer)"}],
                    "redirects": [{"from": "Dani Pedrosa (racer)", "to": "Dani Pedrosa"}],
                    "pages": [
                        {"title": "Dani Pedrosa", "revisions": [{"revid": 111}]},
                        {"title": "Nobody", "missing": True},
                    ],
                }
            },
        )

    result = make_client(handler).latest_revisions(["dani Pedrosa (racer)", "Nobody"])

    assert result["dani Pedrosa (racer)"] == PageRevision("dani Pedrosa (racer)", "Dani Pedrosa", 111)
    assert result["Nobody"] == PageRevision("Nobody", "Nobody", None)


def test_latest_revisions_sends_expected_params():
    seen: list[httpx.QueryParams] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params)
        return httpx.Response(200, json={"query": {"pages": [{"title": "A", "revisions": [{"revid": 1}]}]}})

    make_client(handler).latest_revisions(["A"])

    params = seen[0]
    assert (params["action"], params["prop"], params["rvprop"], params["titles"]) == ("query", "revisions", "ids", "A")
    assert (params["redirects"], params["format"], params["formatversion"]) == ("1", "json", "2")


def test_latest_revisions_batches_by_50_titles():
    batches: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        titles = request.url.params["titles"].split("|")
        batches.append(titles)
        pages = [{"title": t, "revisions": [{"revid": i}]} for i, t in enumerate(titles)]
        return httpx.Response(200, json={"query": {"pages": pages}})

    titles = [f"Rider {i}" for i in range(120)]
    result = make_client(handler).latest_revisions(titles)

    assert [len(b) for b in batches] == [50, 50, 20]
    assert set(result) == set(titles)


def test_fetch_html_requests_parse_by_oldid():
    seen: list[httpx.QueryParams] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params)
        return httpx.Response(200, json={"parse": {"title": "X", "revid": 42, "text": "<div>ok</div>"}})

    assert make_client(handler).fetch_html(42) == "<div>ok</div>"
    params = seen[0]
    assert (params["action"], params["oldid"], params["prop"], params["formatversion"]) == ("parse", "42", "text", "2")


def test_requests_go_to_the_api_endpoint_with_user_agent():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"parse": {"text": "<p/>"}})

    make_client(handler).fetch_html(1)

    assert (seen[0].url.host, seen[0].url.path) == ("en.wikipedia.org", "/w/api.php")
    assert seen[0].headers["User-Agent"] == USER_AGENT


def test_fetch_html_raises_on_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": {"code": "nosuchrevid", "info": "There is no revision 42."}})

    with pytest.raises(WikiRequestError, match="nosuchrevid"):
        make_client(handler).fetch_html(42)


def test_retries_on_503_then_succeeds():  # Review Focus 4
    responses = iter(
        [
            httpx.Response(503),
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json={"parse": {"text": "<p>ok</p>"}}),
        ]
    )
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return next(responses)

    sleeps: list[float] = []
    assert make_client(handler, sleeps).fetch_html(1) == "<p>ok</p>"
    assert len(calls) == 3
    assert sleeps == [1.0, 7.0, 0]  # backoff, then Retry-After, then the inter-request pause


def test_retries_on_transport_error():
    attempts = iter([httpx.ConnectError("boom"), None])

    def handler(request: httpx.Request) -> httpx.Response:
        error = next(attempts)
        if error is not None:
            raise error
        return httpx.Response(200, json={"parse": {"text": "<p>ok</p>"}})

    assert make_client(handler).fetch_html(1) == "<p>ok</p>"


def test_raises_after_max_retries():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503)

    sleeps: list[float] = []
    with pytest.raises(WikiRequestError):
        make_client(handler, sleeps).fetch_html(1)
    assert len(calls) == MAX_ATTEMPTS
    assert sleeps == [1.0, 2.0, 4.0]


def test_does_not_retry_client_errors():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(404)

    with pytest.raises(WikiRequestError):
        make_client(handler).fetch_html(1)
    assert len(calls) == 1


def test_cache_roundtrip(tmp_path):
    cache = HtmlCache(tmp_path / "raw")
    assert cache.get(7) is None
    assert not cache.has(7)
    cache.put(7, "<p>x</p>")
    assert cache.has(7)
    assert cache.get(7) == "<p>x</p>"
    assert (tmp_path / "raw" / "7.html").read_text(encoding="utf-8") == "<p>x</p>"
