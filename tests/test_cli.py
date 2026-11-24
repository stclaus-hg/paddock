from datetime import date

import pytest

from paddock import cli
from paddock.ingest.manifest import Manifest, ManifestPage, PageKind, read_manifest, write_manifest
from paddock.ingest.snapshot import IncompleteSeasonError

OLD = Manifest(date(2026, 1, 1), 2002, 2024, (ManifestPage(PageKind.RIDER, "Old", 1),), {})
NEW = Manifest(date(2026, 11, 23), 2002, 2025, (ManifestPage(PageKind.RIDER, "New", 2),), {})


@pytest.fixture
def manifest_path(tmp_path, monkeypatch):
    path = tmp_path / "snapshot" / "manifest.json"
    monkeypatch.setenv("PADDOCK_MANIFEST", str(path))
    monkeypatch.setenv("PADDOCK_CACHE_DIR", str(tmp_path / "raw"))
    write_manifest(OLD, path)
    return path


def test_snapshot_command_writes_manifest_only_on_success(manifest_path, monkeypatch):  # Review Focus 4
    def failing(*args, **kwargs):
        raise IncompleteSeasonError(2006, ["2006 Broken motorcycle Grand Prix"])

    monkeypatch.setattr(cli, "build_snapshot", failing)
    assert cli.main(["ingest", "snapshot"]) == 1
    assert read_manifest(manifest_path) == OLD

    monkeypatch.setattr(cli, "build_snapshot", lambda *args, **kwargs: NEW)
    assert cli.main(["ingest", "snapshot"]) == 0
    assert read_manifest(manifest_path) == NEW


def test_unknown_command_returns_nonzero():
    assert cli.main(["ingest", "nonsense"]) != 0
    assert cli.main([]) != 0
