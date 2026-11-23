import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from http import HTTPStatus
from itertools import batched
from typing import Any

import httpx
import structlog

# httpx always appends "/" to base_url, so the endpoint file must be passed per request, not baked into the base.
API_BASE_URL = "https://en.wikipedia.org/w/"
API_PATH = "api.php"
USER_AGENT = "paddock/0.1 (learning project)"
HTTP_TIMEOUT_S = 30  #: seconds before a single Wikipedia API request is abandoned
REQUEST_INTERVAL_S = 0.5  #: pause after every successful request, to stay polite to Wikipedia
MAX_TITLES_PER_QUERY = 50  #: MediaWiki limit on titles per query for anonymous clients
MAX_ATTEMPTS = 4  #: total tries per request, including the first one
RETRY_BASE_DELAY_S = 1.0  #: first backoff delay; doubles after each failed attempt

log = structlog.get_logger()


class WikiRequestError(Exception):
    """A Wikipedia API request failed for good (retries exhausted, client error or API error)."""


@dataclass(frozen=True)
class PageRevision:
    requested_title: str
    canonical_title: str
    revid: int | None  #: None means the page does not exist


def make_http_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        base_url=API_BASE_URL, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT_S, transport=transport
    )


def _is_retryable(status: int) -> bool:
    return status == HTTPStatus.TOO_MANY_REQUESTS or status >= HTTPStatus.INTERNAL_SERVER_ERROR


def _retry_after_s(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After", "")
    return float(value) if value.isdigit() else None


class WikiClient:
    def __init__(
        self,
        http: httpx.Client,
        request_interval_s: float = REQUEST_INTERVAL_S,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http
        self._request_interval_s = request_interval_s
        self._sleep = sleep

    def latest_revisions(self, titles: Sequence[str]) -> dict[str, PageRevision]:
        result: dict[str, PageRevision] = {}
        for batch in batched(titles, MAX_TITLES_PER_QUERY, strict=False):
            body = self._get(
                {"action": "query", "prop": "revisions", "rvprop": "ids", "redirects": 1, "titles": "|".join(batch)}
            )
            query = body["query"]
            normalized = {n["from"]: n["to"] for n in query.get("normalized", [])}
            redirects = {r["from"]: r["to"] for r in query.get("redirects", [])}
            pages = {p["title"]: p for p in query.get("pages", [])}
            for title in batch:
                canonical = normalized.get(title, title)
                canonical = redirects.get(canonical, canonical)
                result[title] = PageRevision(title, canonical, _revid_of(pages.get(canonical)))
        return result

    def fetch_html(self, revid: int) -> str:
        body = self._get({"action": "parse", "oldid": revid, "prop": "text"})
        html: str = body["parse"]["text"]
        return html

    def _get(self, params: Mapping[str, str | int]) -> dict[str, Any]:
        full_params = {**params, "format": "json", "formatversion": 2}
        delay = RETRY_BASE_DELAY_S
        for attempt in range(1, MAX_ATTEMPTS + 1):
            wait: float | None = None
            try:
                response = self._http.get(API_PATH, params=full_params)
            except httpx.TransportError as exc:
                if attempt == MAX_ATTEMPTS:
                    raise WikiRequestError(f"Wikipedia request failed: {exc}") from exc
                log.warning("wiki.retry", attempt=attempt, error=str(exc))
            else:
                if response.is_success:
                    body: dict[str, Any] = response.json()
                    if "error" in body:
                        error = body["error"]
                        raise WikiRequestError(f"Wikipedia API error {error.get('code')}: {error.get('info')}")
                    self._sleep(self._request_interval_s)
                    return body
                if not _is_retryable(response.status_code) or attempt == MAX_ATTEMPTS:
                    raise WikiRequestError(f"Wikipedia request failed with HTTP {response.status_code}")
                log.warning("wiki.retry", attempt=attempt, status=response.status_code)
                wait = _retry_after_s(response)
            self._sleep(wait if wait is not None else delay)
            delay *= 2
        raise AssertionError("unreachable")  # pragma: no cover


def _revid_of(page: Mapping[str, Any] | None) -> int | None:
    if page is None or page.get("missing") or page.get("invalid") or not page.get("revisions"):
        return None
    revid: int = page["revisions"][0]["revid"]
    return revid
