import os
from pathlib import Path


class HtmlCache:
    """Page HTML on disk, one file per Wikipedia revision id."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, revid: int) -> Path:
        return self._root / f"{revid}.html"

    def get(self, revid: int) -> str | None:
        path = self._path(revid)
        return path.read_text(encoding="utf-8") if path.exists() else None

    def has(self, revid: int) -> bool:
        return self._path(revid).exists()

    def put(self, revid: int, html: str) -> None:
        # Write-then-rename: an interrupted run must never leave a truncated file that looks cached.
        self._root.mkdir(parents=True, exist_ok=True)
        tmp = self._path(revid).with_suffix(".tmp")
        tmp.write_text(html, encoding="utf-8")
        os.replace(tmp, self._path(revid))
